"""Reserve before each external request; commit counters even when a response is lost."""
import asyncio
from copy import deepcopy
from datetime import timezone
from uuid import uuid4
from sqlalchemy import select
from ..accounts.database import Operation, User
from ..errors import AppError
from .database import Checkpoint, Usage
from .jobs import DurableJobs


class JobBudgets(DurableJobs):
    def activate_for_publication(self, claim):
        """Resume the charged operation's exclusive lease without a fictitious model call."""
        with self.database.session() as session:
            row = self._active(session,claim)
            user = session.get(User,row.user_id)
            quota = self.accounts._quota(session,user.identity)
            operation = session.get(Operation,row.ai_operation_id) if row.ai_operation_id else None
            if not operation or operation.user_id != row.user_id or not operation.charged or operation.kind != 'quiz':
                raise AppError('KNOWLEDGE_QUIZ_NOT_REVIEWED','关卡尚未完成生成与审核',409)
            if quota.busy_id and quota.busy_id != operation.id and quota.busy_until > self.accounts.clock():
                raise AppError('AI_BUSY','正在等待当前学习操作结束后发布关卡',409)
            if operation.status == 'succeeded':
                raise AppError('KNOWLEDGE_RESULT_CONFLICT','原关卡已发布，请查询原任务',409)
            operation.status,operation.error_code = 'running',None
            quota.busy_id,quota.busy_until = operation.id,row.deadline_at.replace(tzinfo=timezone.utc).timestamp()+15

    async def wait_publication(self, claim, *, sleep=asyncio.sleep):
        while True:
            try:
                await asyncio.to_thread(self.activate_for_publication,claim)
                return
            except AppError as error:
                if error.code != 'AI_BUSY': raise
                with self.database.session() as session:
                    row = self._active(session,claim)
                    if (row.deadline_at-self.now()).total_seconds() <= 1:
                        raise AppError('KNOWLEDGE_JOB_EXPIRED','发布等待超过原任务期限',409)
                    row.stage,row.retry_after_seconds = 'waiting_ai',1
                await sleep(1)

    def model_call(self, claim, limit, *, phase=None,reserve=0):
        with self.database.session() as session:
            row = self._active(session,claim)
            user = session.get(User,row.user_id)
            quota = self.accounts._quota(session,user.identity)
            if quota.busy_id and quota.busy_id != row.ai_operation_id and quota.busy_until > self.accounts.clock():
                raise AppError('AI_BUSY','请等待当前生成完成，知识库任务会在原期限内继续等待',409)
            budget = dict(row.budget)
            if budget.get('model_calls',0) >= limit-reserve or (phase == 'retrieval' and budget.get('retrieval_model_calls',0) >= self.accounts.settings.retrieval_model_call_limit):
                raise AppError('KNOWLEDGE_BUDGET_EXHAUSTED','本次任务模型调用预算已用完',429)
            operation = session.get(Operation,row.ai_operation_id) if row.ai_operation_id else None
            if operation is None:
                kind = {'quiz':'quiz','prepare':'material','question':'knowledgeqa'}.get(row.kind)
                if kind is None: raise AppError('INVALID_OPERATION','此任务无需语言模型调用',409)
                operation = Operation(id=str(uuid4()),user_id=row.user_id,key='knowledge:'+row.operation_id,
                                      digest=row.digest,kind=kind,deadline_at=row.deadline_at)
                session.add(operation)
                session.flush()
                row.ai_operation_id = operation.id
            if operation.status == 'succeeded':
                raise AppError('KNOWLEDGE_JOB_STALE','操作已发布，请查询原结果',409)
            operation.status, operation.error_code = 'running', None
            if not operation.charged:
                if row.kind == 'question' and not budget.get('question_reserved'):
                    usage = self._usage(session,user.identity)
                    if usage.questions >= self.config.question_daily_limit:
                        raise AppError('KNOWLEDGE_QUESTION_DAILY_LIMIT','今天的知识库问答次数已用完，请明天再试',429)
                    usage.questions += 1
                elif row.kind == 'prepare' and not budget.get('prepare_reserved'):
                    if quota.topic_prepare_count >= self.accounts.settings.topic_prepare_daily_limit:
                        raise AppError('TOPIC_PREPARE_DAILY_LIMIT','今天的学习范围准备次数已用完',429)
                    quota.topic_prepare_count += 1
            quota.busy_id = operation.id
            quota.busy_until = row.deadline_at.replace(tzinfo=timezone.utc).timestamp()+15
            self.accounts._model_call(session,row.user_id,operation.id)
            budget['model_calls'] = budget.get('model_calls',0)+1
            if phase == 'retrieval': budget['retrieval_model_calls'] = budget.get('retrieval_model_calls',0)+1
            row.budget, row.retry_after_seconds = budget, 0
            return limit-budget['model_calls']

    async def wait_model_call(self, claim, limit, *, phase=None,reserve=0,sleep=asyncio.sleep):
        while True:
            try:
                return await asyncio.to_thread(self.model_call,claim,limit,phase=phase,reserve=reserve)
            except AppError as error:
                if error.code not in ('AI_BUSY','AI_RATE_LIMIT'): raise
                with self.database.session() as session:
                    row = self._active(session,claim)
                    remaining = (row.deadline_at-self.now()).total_seconds()
                    if remaining <= 1: raise AppError('KNOWLEDGE_JOB_EXPIRED','等待模型额度已超过原任务期限',409)
                    row.stage, row.retry_after_seconds = 'waiting_ai', min(5,max(1,int(remaining)))
                    delay = row.retry_after_seconds
                await sleep(delay)

    def reserve_embedding(self, claim, request_id, tokens):
        if type(tokens) is not int or tokens < 1 or not isinstance(request_id,str) or not 1 <= len(request_id) <= 64:
            raise ValueError('Invalid embedding reservation')
        with self.database.session() as session:
            row = self._active(session,claim)
            name = 'embedding:'+request_id
            old = session.get(Checkpoint,(row.operation_id,name))
            if old:
                if old.content['reserved'] != tokens: raise ValueError('Reservation identity reused')
                return deepcopy(old.content)
            user = session.get(User,row.user_id)
            usage = self._usage(session,user.identity)
            if usage.embedding_reserved+usage.embedding_actual+tokens > self.config.embedding_daily_tokens:
                raise AppError('KNOWLEDGE_EMBEDDING_DAILY_LIMIT','今天的向量化额度不足，请减少资料或明天再试',429)
            usage.embedding_reserved += tokens
            content = {'identity':user.identity,'day':usage.day,'reserved':tokens,'actual':None}
            session.add(Checkpoint(operation_id=row.operation_id,name=name,user_id=row.user_id,content=content))
            budget = dict(row.budget)
            budget['embedding_requests'] = budget.get('embedding_requests',0)+1
            budget['embedding_tokens_reserved'] = budget.get('embedding_tokens_reserved',0)+tokens
            row.budget = budget
            return deepcopy(content)

    def settle_embedding(self, claim, request_id, actual):
        if type(actual) is not int or actual < 0: raise ValueError('Invalid provider usage')
        with self.database.session() as session:
            # Paid responses may arrive after cancellation. Settling cannot publish content.
            self.accounts._user(session,claim.user_id,True)
            checkpoint = session.scalar(select(Checkpoint).where(Checkpoint.operation_id == claim.operation_id,
                Checkpoint.name == 'embedding:'+request_id,Checkpoint.user_id == claim.user_id).with_for_update())
            if checkpoint is None: raise AppError('KNOWLEDGE_RESERVATION_MISSING','向量用量预留不存在',409)
            content = dict(checkpoint.content)
            if content['actual'] is not None: return
            usage = session.scalar(select(Usage).where(Usage.identity == content['identity'],Usage.day == content['day']).with_for_update())
            if usage is None: raise AppError('KNOWLEDGE_RESERVATION_MISSING','向量用量记录不存在',409)
            usage.embedding_reserved -= content['reserved']
            usage.embedding_actual += actual
            content['actual'] = actual
            checkpoint.content = content
