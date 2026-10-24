"""Knowledge scopes enter the existing quiz and learning publication path."""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from uuid import uuid4
from sqlalchemy import select
from ..errors import AppError
from ..model_transport import run_model_job
from ..models import GenerateRequest,Quiz
from ..quiz_grounding.generation import generate_grounded,DRAFT_VERSION,REVIEW_VERSION
from ..quiz_grounding.runtime import counted_gateway
from .database import Job
from .models import QuizRequest
from .scopes import ScopeRepository
from .retrieval_store import KnowledgeRetriever


class QuizRepository(ScopeRepository):
    def submit_quiz(self, uid, key, body):
        body = QuizRequest.model_validate(body)
        if not isinstance(key,str) or not 1 <= len(key) <= 128: raise AppError('INVALID_INPUT','操作标识不正确',422)
        identity = body.model_dump(mode='json')
        if not body.generate_images:
            identity.pop('generate_images')  # Legacy queued tasks keep their identity.
        identity['candidate_ids'] = sorted(identity['candidate_ids'])
        hashed = hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        with self.database.session() as session:
            user = self.accounts._user(session,uid,True)
            old = session.scalar(select(Job).where(Job.user_id == uid,Job.kind == 'quiz',Job.key == key))
            if old:
                if old.digest != hashed: raise AppError('IDEMPOTENCY_CONFLICT','相同标识的确认范围或题目设置不同',409)
                return self._public_job_data(session,old)
            context = self.confirm_scope(uid,body.scope_id,body.scope_version,body.candidate_ids,supplement=body.supplement,session=session)
            quota = self.accounts._quota(session,user.identity)
            if quota.quiz_count >= self.accounts.settings.quiz_daily_limit:
                raise AppError('DAILY_QUOTA_EXCEEDED','今天的出题额度已用完，明天再来吧',429)
            scope = self._scope(session,uid,body.scope_id)
            context['prepared_at'] = scope.created_at.replace(tzinfo=timezone.utc).isoformat()
            duration=self.config.quiz_timeout_seconds
            if body.generate_images:
                from ..question_images.service import stage_budget
                duration+=stage_budget()
            row = Job(id=str(uuid4()),user_id=uid,kind='quiz',key=key,digest=hashed,operation_id=str(uuid4()),priority=5,
                payload={'selection':identity,'documents':deepcopy(context['documents']),'context':context},
                deadline_at=self.now()+timedelta(seconds=duration),created_at=self.now())
            session.add(row)
            session.flush()
            return self.job_data(row)


class CheckpointGateway:
    def __init__(self, pipeline, claim, gateway):
        self.pipeline,self.claim,self.gateway = pipeline,claim,gateway
        self.counts = {}

    @staticmethod
    def name(schema,number): return f'quiz:{schema}:{number}'

    async def generate(self, schema, prompt, check=None):
        index = self.counts.get(schema.__name__,0)
        self.counts[schema.__name__] = index+1
        name = self.name(schema.__name__,index)
        signature = hashlib.sha256(prompt.encode()).hexdigest()
        old = await asyncio.to_thread(self.pipeline.read_checkpoint,self.claim,name)
        if old:
            if old['prompt_hash'] != signature: raise AppError('KNOWLEDGE_CHECKPOINT_CHANGED','生成策略或资料已变化，请重新发起',409)
            result = schema.model_validate(old['result'])
            if check: check(result)
            return result
        result = schema.model_validate(await self.gateway.generate(schema,prompt,check))
        if check: check(result)
        await asyncio.to_thread(self.pipeline.checkpoint,self.claim,name,{'prompt_hash':signature,'result':result.model_dump(mode='json')},
            stage='generating' if schema.__name__ == 'QuizDraftResult' else 'reviewing',progress=65 if schema.__name__ == 'QuizDraftResult' else 85)
        return result

    def remaining(self):
        with self.pipeline.database.session() as session:
            row = self.pipeline._active(session,self.claim)
            remaining = self.pipeline.accounts.settings.generation_model_call_limit-row.budget.get('model_calls',0)
        for name in ('QuizDraftResult','QuizReview'):
            if self.pipeline.read_checkpoint(self.claim,self.name(name,self.counts.get(name,0))) is not None: remaining += 1
        return remaining


class QuizPipeline(QuizRepository):
    def __init__(self, accounts, config, index, *, gateway=None,retriever=None,images=None):
        super().__init__(accounts,config)
        self.gateway,self.retriever = gateway,retriever or KnowledgeRetriever(accounts,config,index)
        self.images=images

    async def process_async(self, claim):
        old = self.processed_result(claim)
        if old is not None: return old
        selected = QuizRequest.model_validate(claim.payload['selection'])
        context = deepcopy(claim.payload['context'])
        # Scope and permission are rechecked at execution, not merely submission.
        self.confirm_scope(claim.user_id,selected.scope_id,selected.scope_version,selected.candidate_ids,supplement=selected.supplement)
        validated = await asyncio.to_thread(self.read_checkpoint,claim,'validated-quiz')
        if validated:
            if validated['draft_version'] != DRAFT_VERSION or validated['review_version'] != REVIEW_VERSION:
                raise AppError('KNOWLEDGE_CHECKPOINT_CHANGED','出题审核策略已变化，请重新准备',409)
            quiz = Quiz.model_validate(validated['quiz']).model_dump(mode='json')
        else:
            prepared_at = datetime.fromisoformat(context['prepared_at']).replace(tzinfo=None)
            stale = (self.now()-prepared_at).total_seconds()>self.accounts.settings.evidence_reuse_seconds
            if selected.supplement and stale:
                outcome = await self.retriever.retrieve(claim,context['scope']['input_text'],context['documents'],allow_web=True)
                if outcome.knowledge_error and outcome.depends_on_documents and not any(s.knowledge for s in outcome.evidence):
                    raise AppError(outcome.knowledge_error,'资料检索暂不可用，请稍后重试',503)
                context['segments'] = [s.model_dump(mode='json') for s in outcome.evidence]
                context['point_evidence'] = None
                context['supplement_failed'] = bool(outcome.reason_code and not any(s.supplement for s in outcome.evidence))
            if self.gateway is None and not self.accounts.settings.deepseek_api_key.get_secret_value():
                raise AppError('MODEL_NOT_CONFIGURED','请配置学习模型服务后重试',503)
            phase = 'generating'
            async def stage(value):
                nonlocal phase
                phase = value
                await asyncio.to_thread(self.advance,claim,value,55 if value == 'generating' else 75)
            async def before():
                await self.wait_model_call(claim,self.accounts.settings.generation_model_call_limit,reserve=1 if phase == 'generating' else 0)
            gateway = CheckpointGateway(self,claim,counted_gateway(self.accounts.settings,self.gateway,before,claim.operation_id))
            body = GenerateRequest(text=context['scope']['input_text'],question_count=selected.question_count,difficulty=selected.difficulty)
            quiz = await generate_grounded(body,context,gateway,self.accounts.settings,stage=stage,remaining=gateway.remaining)
            quiz = Quiz.model_validate(quiz).model_dump(mode='json')
            await asyncio.to_thread(self.checkpoint,claim,'validated-quiz',{'quiz':quiz,'draft_version':DRAFT_VERSION,'review_version':REVIEW_VERSION},stage='publishing',progress=95)
        if selected.generate_images:
            from ..question_images.service import enrich_quiz
            await asyncio.to_thread(self.advance,claim,'generating_images',95)
            def verify_image_claim():
                with self.database.session() as session:self._active(session,claim)
            async def image_guard():
                await asyncio.to_thread(verify_image_claim)
            async def before_image_plan():
                await self.wait_model_call(claim,self.accounts.settings.generation_model_call_limit)
            image_gateway=counted_gateway(self.accounts.settings,self.gateway,before_image_plan,claim.operation_id)
            quiz=await enrich_quiz(self.accounts,claim.user_id,claim.operation_id,quiz,service=self.images,
                seconds=max(0,(claim.deadline_at-self.now()).total_seconds()-15),guard=image_guard,gateway=image_gateway)
        await self.wait_publication(claim)
        def publish(session,row):
            self.confirm_scope(row.user_id,selected.scope_id,selected.scope_version,selected.candidate_ids,supplement=selected.supplement,session=session)
            return self.accounts.store_quiz(row.user_id,quiz,row.ai_operation_id,session=session)
        return self.complete(claim,publish)

    def process(self, claim): return run_model_job(lambda:self.process_async(claim))
