"""Question retrieval, reviewed answer checkpoints and one-transaction publication."""
import asyncio
from copy import deepcopy
from uuid import uuid5,NAMESPACE_URL
from ..errors import AppError
from ..model_transport import run_model_job
from ..quiz_grounding.runtime import counted_gateway
from .answering import create_answer
from .database import Question
from .questions import QuestionRepository
from .retrieval_store import KnowledgeRetriever


class QuestionPipeline(QuestionRepository):
    def __init__(self, accounts, config, index, *, gateway=None,retriever=None):
        super().__init__(accounts,config)
        self.gateway = gateway
        self.retriever = retriever or KnowledgeRetriever(accounts,config,index)

    def remaining(self, claim):
        with self.database.session() as session:
            row = self._active(session,claim)
            return self.accounts.settings.generation_model_call_limit-row.budget.get('model_calls',0)

    async def process_async(self, claim):
        old = self.processed_result(claim)
        if old is not None: return old
        payload = claim.payload
        outcome = await self.retriever.retrieve(claim,payload['question'],payload['documents'],allow_web=payload['supplement'])
        if outcome.evidence and self.gateway is None and not self.accounts.settings.deepseek_api_key.get_secret_value():
            raise AppError('MODEL_NOT_CONFIGURED','请配置学习模型服务后重试',503)
        phase = 'answering'
        async def stage(value):
            nonlocal phase
            phase = value
            await asyncio.to_thread(self.advance,claim,value,55 if value == 'answering' else 75)
        async def before():
            await self.wait_model_call(claim,self.accounts.settings.generation_model_call_limit,reserve=1 if phase == 'answering' else 0)
        async def read(name): return await asyncio.to_thread(self.read_checkpoint,claim,name)
        async def save(name,content): await asyncio.to_thread(self.checkpoint,claim,name,content,stage=phase,progress=60 if phase == 'answering' else 85)
        gateway = counted_gateway(self.accounts.settings,self.gateway,before,claim.operation_id)
        result = await create_answer(payload['question'],outcome,gateway,remaining=lambda:self.remaining(claim),
            allow_web=payload['supplement'],read_checkpoint=read,save_checkpoint=save,stage=stage)
        return await asyncio.to_thread(self.publish,claim,result)

    def process(self, claim): return run_model_job(lambda:self.process_async(claim))

    def publish(self, claim, content):
        def publication(session,row):
            self.validate_documents(row.user_id,row.payload['documents'],session=session)
            qid = str(uuid5(NAMESPACE_URL,'levelup-knowledge-answer:'+row.operation_id))
            session.add(Question(id=qid,user_id=row.user_id,operation_id=row.operation_id,question=row.payload['question'],
                documents=deepcopy(row.payload['documents']),supplement=int(row.payload['supplement']),content=deepcopy(content),created_at=self.now()))
            session.flush()
            return {'question_id':qid}
        return self.complete(claim,publication)
