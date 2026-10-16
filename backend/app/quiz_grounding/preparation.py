import asyncio
import json
import logging
from typing import Literal

from pydantic import model_validator
from langchain_core.prompts import ChatPromptTemplate

from starlette.concurrency import run_in_threadpool

from ..errors import AppError
from ..llm import ModelGateway
from .agent import RetrievalAgent
from .evidence import EvidenceContextBudget, UNTRUSTED_DATA_RULE
from .models import ScopeContent
from .snapshots import GroundingStatus
from .snapshots import GroundingModel
from .runtime import counted_gateway


SCOPE_VERSION = 'scope-v1'
logger = logging.getLogger(__name__)


class UnreadablePageScope(GroundingModel):
    status: Literal['ready', 'needs_topic']
    scope: ScopeContent | None = None

    @model_validator(mode='after')
    def consistent(self):
        if (self.status == 'ready') != (self.scope is not None):
            raise ValueError('只有明确独立主题才能整理范围')
        if self.scope:
            self.scope.check_evidence(set())
            if any(p.evidence_status != 'unverified' for c in self.scope.candidates for f in c.focuses for p in f.points):
                raise ValueError('不可读网页的主题范围只能标记未核实')
        return self


async def unreadable_page_scope(instruction, gateway):
    prompt = f'''指定网页读取失败。仅判断用户附加说明是否包含可以独立理解的具体学习主题。
“重点学其中案例”等依赖未读页面的说明没有独立主题，必须返回 needs_topic 和 scope=null。
有明确主题时，只基于该主题整理待确认范围；全部知识点 evidence_ids=[]、evidence_status=unverified。
不猜测网址、页面标题或正文；不联网搜索，不声称读过网页。只返回 JSON：
{json.dumps(UnreadablePageScope.model_json_schema(), ensure_ascii=False)}
{UNTRUSTED_DATA_RULE}
用户附加说明：{json.dumps(instruction, ensure_ascii=False)}'''
    return await gateway.generate(UnreadablePageScope, prompt)


def scope_prompt(text, context, reason):
    body = f'''整理待用户确认的学习范围，不出题，不创建关卡。版本 {SCOPE_VERSION}。
保留用户完整意图，同名概念列出合理不同领域，不能用熟悉的领域替代。每次都需要用户确认，即使仅一个候选。
最多 3 个候选领域，每个最多 3 个方向，每方向最多 6 个具体知识点。方向要有实质区别，文化热点应保留资料中的热门梗/名场面及语境方向。
候选按与用户学习目标的相关性排序，第一个作为默认推荐；每个候选会作为一张可多选主题卡片，topic/domain 简明区分内容，description 用一句简短的话说明将学什么，不超过 60 字。避免为了凑数拆分相近主题。
依据实际取得资料建立候选，来源 ID 必须来自本次片段。没有资料的候选允许基于已有知识保留，但 evidence_ids=[] 且 evidence_status=unverified，不能编造引用或声称已联网核实。
有资料也只表示取得依据，最终题目另行审核。网址正文读不到不得根据网址猜测网页内容。
只返回符合 Schema 的 JSON：{json.dumps(ScopeContent.model_json_schema(), ensure_ascii=False)}
用户学习意图：{json.dumps(text, ensure_ascii=False)}
资料不足原因：{json.dumps(reason)}
{context}'''
    return ChatPromptTemplate.from_messages([('human', '{body}')]).format(body=body)


async def process_preparation(state, uid, pid, *, sleep=asyncio.sleep):
    repo = state.grounding
    stage_value = 'planning'

    async def stage(value):
        nonlocal stage_value
        stage_value = value
        await run_in_threadpool(repo.stage, uid, pid, value)

    async def before_model():
        while True:
            wait = await run_in_threadpool(repo.model_call, uid, pid, stage_value)
            if not wait:
                return
            # Short waits allow cancellation/account deletion to stop subsequent work.
            for _ in range(wait):
                await sleep(1)
                current = await run_in_threadpool(repo.get, uid, pid)
                if current['status'] != 'running':
                    raise AppError('OPERATION_CANCELLED', '主题准备已取消或过期', 409)

    async def before_tool(name, pages):
        await run_in_threadpool(repo.tool_call, uid, pid, name, pages)

    async def before_pages(pages):
        await run_in_threadpool(repo.preparation_page_call, uid, pid, pages)

    try:
        initial = await run_in_threadpool(repo.get, uid, pid)
        if initial['status'] != 'running':
            return
        remaining = await run_in_threadpool(repo.preparation_remaining_seconds, uid, pid)
        async with asyncio.timeout(remaining):
            run = RetrievalAgent(state.settings, model=getattr(state, 'retrieval_model', None),
                                 before_model=before_model, before_tool=before_tool, before_pages=before_pages, stage=stage)
            outcome = await run.run(initial['input_text'])
            await stage('summarizing')
            # Reserve a separate half of the phase evidence allowance for scope JSON.
            context = EvidenceContextBudget(state.settings.evidence_max_chars // 2).message(outcome.evidence)
            prompt = scope_prompt(initial['input_text'], context, outcome.reason_code)
            valid_ids = {s.id for s in outcome.evidence}
            def check(result):
                result.check_evidence(valid_ids)
            if state.gateway is None and not state.settings.deepseek_api_key.get_secret_value():
                raise AppError('MODEL_NOT_CONFIGURED', '请配置模型密钥', 503)
            gateway = counted_gateway(state.settings, state.gateway, before_model, pid)
            scope = await gateway.generate(ScopeContent, prompt, check)
            # Never let an injected runner skip the postcondition.
            scope = ScopeContent.model_validate(scope)
            check(scope)
            all_backed = all(p.evidence_status == 'available' and p.evidence_ids
                             for c in scope.candidates for f in c.focuses for p in f.points)
            grounding = GroundingStatus(status='source_backed' if all_backed and outcome.evidence else 'unverified',
                reason_code=None if all_backed and outcome.evidence else outcome.reason_code or 'PARTIAL_EVIDENCE',
                provider='tavily' if outcome.evidence else None,
                retrieved_at=max((s.retrieved_at for s in outcome.evidence), default=None))
            await run_in_threadpool(repo.finish, uid, pid, {
                'scope': scope.model_dump(mode='json'), 'grounding': grounding.model_dump(mode='json'),
                'evidence': [s.model_dump(mode='json') for s in outcome.evidence], 'trace': outcome.trace,
                'usage': outcome.usage, 'scope_prompt_version': SCOPE_VERSION,
            })
    except asyncio.CancelledError:
        await run_in_threadpool(repo.finish, uid, pid, error='OPERATION_INTERRUPTED')
        raise
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else 'OPERATION_EXPIRED' if isinstance(exc, TimeoutError) else 'PREPARATION_FAILED'
        logger.warning('preparation_failed id=%s stage=%s code=%s type=%s', pid, stage_value, code, type(exc).__name__)
        await run_in_threadpool(repo.finish, uid, pid, error=code)
