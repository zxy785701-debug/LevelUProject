"""Confirmed scope -> bounded retrieval -> JSON draft -> independent evidence review."""
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from langchain_core.prompts import ChatPromptTemplate
from starlette.concurrency import run_in_threadpool

from ..errors import AppError
from ..llm import ModelGateway
from .agent import RetrievalAgent
from .evidence import EvidenceContextBudget, UNTRUSTED_DATA_RULE, model_evidence
from .models import QuizDraftResult, QuizReview
from .policy import retrieval_prompt
from .snapshots import EvidenceSegment, GroundingStatus, LearningScopeSnapshot
from .runtime import counted_gateway


DRAFT_VERSION = 'grounded-draft-v2'
FALLBACK_VERSION = 'unverified-draft-v2'
REVIEW_VERSION = 'evidence-review-v2'


def render(instruction, data):
    template = ChatPromptTemplate.from_messages([
        ('system', '{instruction}'), ('human', '{data}')])
    return template.format(instruction=instruction, data=json.dumps(data, ensure_ascii=False, separators=(',', ':')))


def draft_prompt(body, context, evidence, *, correction=None):
    mix = {'single': 1, 'multi': 1, 'judge': 1} if body.question_count == 3 else {'single': 3, 'multi': 1, 'judge': 1}
    material = context.get('material') is not None
    knowledge = context.get('knowledge_policy') == 'strict'
    version = DRAFT_VERSION if evidence or material or knowledge else FALLBACK_VERSION
    instruction = f'''你是严谨的出题者，模板 {version}。完整保留已确认领域、方向和知识点，不切换领域。
出 {body.question_count} 道中文题，难度 {body.difficulty}，题型数量严格为 {json.dumps(mix)}。
单选/多选四个不同 A-D 选项，判断仅 A=正确、B=错误；单选/判断一个答案，多选至少两个。ID 唯一，讲解自包含。
优先依据实际资料。每题 source_ids 只引用直接支持题干、正确答案和讲解的实际片段，不能凭真实 ID 伪装支持。
覆盖用户选定方向，不能只用标题或其他无关常识凑题。争议必须用明确出处限定，不能把有争议的归属写成定论。
如果 selected_topics 非空，每个已选主题都至少覆盖一个知识点；可以用比较题同时覆盖多个主题，不得忽略任何已选主题。
材料的自动标题和知识点只作为内容线索；在所选片段范围内，优先满足 input_text / focus 中的原始学习说明。要求比较、机制或应用时不能用附近的背景常识替代；资料无法支持该要求时返回 insufficient_knowledge。
{'本次为知识库学习，只能依据所选知识库资料及明确补充片段。资料不足返回 insufficient_knowledge，不能用外部常识填满。' if knowledge else '本次为材料学习，只能依据所选原材料及明确补充片段。原材料不足就返回 insufficient_knowledge，不能用外部常识填满。' if material else '资料缺失时允许基于同一确认主题的可靠已有知识出题，source_ids=[]，将由程序标为未联网核实；不确定的知识不要编造，不足时返回 insufficient_knowledge。'}
不要自行设置 grounding，核实状态由独立审核及程序决定。修正任务必须逐项处理审核发现，不改用户范围。
{UNTRUSTED_DATA_RULE}
只输出符合 Schema 的 JSON：{json.dumps(QuizDraftResult.model_json_schema(), ensure_ascii=False)}'''
    return render(instruction, {'confirmed_scope': context['scope'], 'evidence': [model_evidence(s) for s in evidence],
                                'correction': correction})


def review_prompt(context, quiz, evidence):
    instruction = f'''你是独立的无工具事实审核员，模板 {REVIEW_VERSION}。不采信出题者的自评。
逐题核对题干、正确选项、排除其他选项的理由和讲解；仅按下面实际片段判断是否得到支持。
supported=片段直接支持且无冲突；unsupported=没有充分支持但未发现确定矛盾；contradicted=有明确错误；ambiguous=争议/含混不能当唯一结论；off_scope=偏离确认范围。
来源真实或 ID 存在不等于支持结论。摘要只支持其实际写出的内容；缺失和截断部分不作证据。
有争议的梗/归属要核对语境与限定，转载同文不算独立来源。已有知识不能用于把 unsupported 升级为 supported，但能用于指出明确常识错误。
检查选定方向实质覆盖，不能把“热门梗”替换为演员或节目名基本信息。covered_point_ids 只能是已选知识点 ID。
如果 selected_topics 非空，逐一检查每个主题至少一个知识点得到实质覆盖；缺少任一主题时 focus_covered=false。covered_point_ids 必须如实记录各主题实际覆盖的知识点。
原始学习说明 input_text 与确认方向 focus 必须得到实质回应；自动标题或摘要知识点不构成放宽范围的理由。要求比较、机制或应用而题目只问一般背景时，判 off_scope 或 focus_covered=false。
返回每题且仅一次，必须有解释理由；supported 必须有有效片段 ID。禁止修改工具或联网，禁止自行修正题目后假称审核通过。
{UNTRUSTED_DATA_RULE}
只返回 JSON：{json.dumps(QuizReview.model_json_schema(), ensure_ascii=False)}'''
    return render(instruction, {'confirmed_scope': context['scope'], 'quiz': quiz.model_dump(mode='json'),
                                'evidence': [model_evidence(s) for s in evidence]})


def review_decision(quiz, review, evidence, context):
    questions = {q.id: q for q in quiz.questions}
    if {r.question_id for r in review.questions} != set(questions):
        raise AppError('MODEL_INVALID_OUTPUT', '审核未覆盖所有题目', 502)
    selected_ids = set(context['scope'].get('scope_point_ids') or [])
    if selected_ids and not set(review.covered_point_ids) <= selected_ids:
        raise AppError('MODEL_INVALID_OUTPUT', '审核包含未选择的知识点', 502)
    bad = [r for r in review.questions if r.status in ('contradicted', 'ambiguous', 'off_scope')]
    if bad or not review.focus_covered:
        return False
    if any(not set(topic['scope_point_ids']).intersection(review.covered_point_ids)
           for topic in context['scope'].get('selected_topics', [])):
        return False
    sources = {s.id: s for s in evidence}
    for verdict in review.questions:
        question = questions[verdict.question_id]
        valid = verdict.status == 'supported' and verdict.source_ids and set(verdict.source_ids) <= set(sources)
        if valid:
            question.source_ids = verdict.source_ids
            network = any(sources[sid].content_kind != 'material' for sid in verdict.source_ids)
            question.grounding = GroundingStatus(status='source_backed' if network else 'material_only',
                provider='tavily' if network else None,
                check_version=REVIEW_VERSION,
                retrieved_at=max((sources[sid].retrieved_at for sid in verdict.source_ids if sources[sid].retrieved_at), default=None))
        else:
            question.source_ids = []
            question.grounding = GroundingStatus(status='unverified', reason_code='INSUFFICIENT_SUPPORT', check_version=REVIEW_VERSION)
    if (context.get('material') or context.get('knowledge_policy') == 'strict') and any(q.grounding.status == 'unverified' for q in quiz.questions):
        return False  # Material-only failure cannot turn into unrelated model knowledge.
    return True


async def generate_grounded(body, context, gateway, settings, *, stage, remaining):
    segments = [EvidenceSegment.model_validate(s) for s in context['segments']]
    evidence = EvidenceContextBudget(settings.evidence_max_chars).select(segments, context.get('point_evidence'))
    knowledge = context.get('knowledge_policy') == 'strict'
    if knowledge and not evidence:
        raise AppError('INSUFFICIENT_KNOWLEDGE','所选知识库没有充分依据，请补充资料或缩小范围',422)
    mix = Counter({'single': 1, 'multi': 1, 'judge': 1} if body.question_count == 3 else {'single': 3, 'multi': 1, 'judge': 1})
    def check_draft(draft):
        if draft.status == 'ready' and Counter(q.type for q in draft.quiz.questions) != mix:
            raise AppError('MODEL_INVALID_OUTPUT', '草稿题量或题型不正确', 502)
    correction = None
    while True:
        await stage('generating')
        draft = await gateway.generate(QuizDraftResult, draft_prompt(body, context, evidence, correction=correction), check_draft)
        draft = QuizDraftResult.model_validate(draft)
        check_draft(draft)
        if draft.status == 'insufficient_knowledge':
            raise AppError('INSUFFICIENT_KNOWLEDGE', '该范围知识或材料不足，请缩小范围或补充资料', 422)
        quiz = draft.quiz
        # AI-authored grounding labels are never authoritative.
        for question in quiz.questions:
            question.grounding = None
            question.origin = None
        await stage('reviewing')
        review = await gateway.generate(QuizReview, review_prompt(context, quiz, evidence))
        review = QuizReview.model_validate(review)
        if review_decision(quiz, review, evidence, context):
            break
        if remaining() < 2:
            raise AppError('QUIZ_REVIEW_FAILED', '题目依据或学习方向未通过审核，请补充资料后重试', 502)
        correction = {'previous_quiz': quiz.model_dump(mode='json'), 'review': review.model_dump(mode='json')}
    unverified = any(q.grounding.status == 'unverified' for q in quiz.questions)
    failed_supplement = context.get('supplement_failed', False)
    status = 'unverified' if unverified or failed_supplement and not knowledge else 'source_backed' if any(q.grounding.status == 'source_backed' for q in quiz.questions) else 'material_only'
    cited = {sid for q in quiz.questions for sid in q.source_ids}
    provenance = [s for s in evidence if s.id in cited and s.content_kind != 'material'] if knowledge else evidence
    grounding = GroundingStatus(status=status, reason_code='SUPPLEMENT_FAILED' if failed_supplement else context.get('fallback_reason') or 'INSUFFICIENT_SUPPORT' if unverified else None,
        check_version=REVIEW_VERSION,
        provider='tavily' if any(s.content_kind != 'material' for s in provenance) else None,
        retrieved_at=max((s.retrieved_at for s in provenance if s.retrieved_at), default=None))
    material = context.get('material')
    used = {s.id: s for s in evidence}
    source = {'type': 'knowledge_base' if knowledge else material['source_type'] if material else 'topic', 'title': '我的知识库' if knowledge else material['title'] if material else context['scope']['topic'],
              'segments': [s.model_copy(update={'context_truncated': used[s.id].context_truncated}).model_dump(mode='json') for s in segments if s.id in cited]}
    if material:
        source.update(material_id=material['id'], url=material.get('url'))
    return {**quiz.model_dump(mode='json'), 'id': str(uuid4()), 'created_at': datetime.now(timezone.utc).isoformat(),
            'source_text': context['scope']['input_text'], 'difficulty': body.difficulty,
            'learning_scope': context['scope'], 'grounding': grounding.model_dump(mode='json'), 'source': source}


async def process_generation(state, uid, oid, body, context, *, sleep=asyncio.sleep):
    repo, settings = state.grounding, state.settings
    calls = 0
    phase = 'retrieving'
    reserve = 2

    async def stage(value):
        nonlocal phase, reserve
        phase = value
        reserve = 1 if value == 'generating' else 0 if value == 'reviewing' else 2
        await run_in_threadpool(repo.generation_stage, uid, oid, value)

    async def before_model():
        nonlocal calls
        if calls >= settings.generation_model_call_limit - reserve:
            raise AppError('MODEL_BUDGET_EXHAUSTED', '本次调用预算不足以完成审核', 409)
        while True:
            wait = await run_in_threadpool(repo.generation_model_call, uid, oid, body.execution == 'background', phase)
            if not wait:
                calls += 1
                return
            await sleep(min(wait, 1))

    async def before_tool(name, pages):
        await run_in_threadpool(repo.generation_tool_call, uid, oid, name, pages)

    async def before_pages(pages):
        await run_in_threadpool(repo.operation_page_call, uid, oid, pages)

    try:
        remaining_seconds = await run_in_threadpool(repo.remaining_seconds, uid, oid)
        async with asyncio.timeout(remaining_seconds):
            material = context.get('material')
            segments = [EvidenceSegment.model_validate(s) for s in context['segments']]
            now = datetime.now(timezone.utc)
            stale = not segments or any(not s.retrieved_at or (now - s.retrieved_at).total_seconds() > settings.evidence_reuse_seconds for s in segments)
            page_fallback = (context.get('grounding') or {}).get('reason_code') == 'PAGE_UNREADABLE'
            retrieve = body.supplement if material else stale and not page_fallback
            if retrieve:
                run = RetrievalAgent(settings, model=getattr(state, 'retrieval_model', None),
                    before_model=before_model, before_tool=before_tool, before_pages=before_pages, stage=stage)
                scope = context['scope']
                retrieval_task = (
                    f"请为用户的原始学习任务查证：{scope['input_text']}\n"
                    f"已确认方向：{scope['focus']}\n"
                    '只补齐完成这一任务所缺的资料。材料自动标题和摘要知识点是检索线索，不能替代上述学习任务。\n'
                    f"完整范围快照：{json.dumps(scope, ensure_ascii=False)}"
                )
                outcome = await run.run(retrieval_task,
                                        system_prompt=retrieval_prompt(confirmed_scope=context['scope']))
                await run_in_threadpool(repo.record_retrieval, uid, oid, outcome)
                if material:
                    extras = [s.model_copy(update={'supplement': True}) for s in outcome.evidence]
                    context['segments'] += [s.model_dump(mode='json') for s in extras]
                    context['supplement_failed'] = not bool(extras)
                elif outcome.evidence:
                    context['segments'] = [s.model_dump(mode='json') for s in outcome.evidence]
                    context['point_evidence'] = None
                else:
                    # Stale sources must not be presented as newly verified after a failed refresh.
                    context['segments'], context['point_evidence'] = [], None
                    context['fallback_reason'] = outcome.reason_code
            if state.gateway is None and not settings.deepseek_api_key.get_secret_value():
                raise AppError('MODEL_NOT_CONFIGURED', '请配置模型密钥', 503)
            gateway = counted_gateway(settings, state.gateway, before_model, oid)
            quiz = await generate_grounded(body, context, gateway, settings, stage=stage,
                                          remaining=lambda: settings.generation_model_call_limit - calls)
            await run_in_threadpool(state.accounts.store_quiz, uid, quiz, oid)
    except asyncio.CancelledError:
        await run_in_threadpool(state.accounts.finish, uid, oid, None, 'OPERATION_INTERRUPTED')
        raise
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else 'OPERATION_EXPIRED' if isinstance(exc, TimeoutError) else 'MODEL_INVALID_OUTPUT'
        await run_in_threadpool(state.accounts.finish, uid, oid, None, code)
