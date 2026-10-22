"""Immutable, version-bound learning scopes with one-level topic selection."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from typing import Literal
from uuid import uuid4,uuid5,NAMESPACE_URL
from pydantic import model_validator
from sqlalchemy import select
from ..errors import AppError
from ..model_transport import run_model_job
from ..models import StrictModel
from ..accounts.repository import stamp
from ..quiz_grounding.models import ScopeContent
from ..quiz_grounding.selection import topic_selection
from ..quiz_grounding.evidence import UNTRUSTED_DATA_RULE,model_evidence
from ..quiz_grounding.runtime import counted_gateway
from .database import Job,Scope
from .budgets import JobBudgets
from .models import ScopeRequest
from .retrieval_store import KnowledgeRetriever


class ScopeDraft(StrictModel):
    status: Literal['ready','insufficient']
    scope: ScopeContent | None = None
    reason: str | None = None

    @model_validator(mode='after')
    def consistent(self):
        if (self.status == 'ready') != (self.scope is not None): raise ValueError('范围状态与内容不一致')
        return self


class ScopeRepository(JobBudgets):
    def submit_preparation(self, uid, key, body):
        body = ScopeRequest.model_validate(body)
        if not isinstance(key,str) or not 1 <= len(key) <= 128: raise AppError('INVALID_INPUT','操作标识不正确',422)
        hashed = hashlib.sha256(json.dumps(body.model_dump(mode='json'),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        with self.database.session() as session:
            user = self.accounts._user(session,uid,True)
            old = session.scalar(select(Job).where(Job.user_id == uid,Job.kind == 'prepare',Job.key == key))
            if old:
                if old.digest != hashed: raise AppError('IDEMPOTENCY_CONFLICT','相同标识的目标、资料或联网权限不同',409)
                return self.job_data(old)
            selected = self._selection(session,uid,body.document_ids,body.all_ready)
            quota = self.accounts._quota(session,user.identity)
            if quota.topic_prepare_count >= self.accounts.settings.topic_prepare_daily_limit:
                raise AppError('TOPIC_PREPARE_DAILY_LIMIT','今天的学习范围准备次数已用完',429)
            quota.topic_prepare_count += 1
            row = Job(id=str(uuid4()),user_id=uid,kind='prepare',key=key,digest=hashed,operation_id=str(uuid4()),
                payload={'goal':body.goal,'documents':selected,'supplement':body.supplement},budget={'prepare_reserved':1},
                priority=15,deadline_at=self.now()+timedelta(seconds=self.config.preparation_timeout_seconds),created_at=self.now())
            session.add(row)
            session.flush()
            return self.job_data(row)

    def _scope(self, session, uid, sid):
        scope = session.scalar(select(Scope).where(Scope.id == sid,Scope.user_id == uid))
        if scope is None: raise AppError('NOT_FOUND','学习范围不存在',404)
        if scope.expires_at <= self.now(): raise AppError('KNOWLEDGE_SCOPE_EXPIRED','学习范围已过期，请重新准备',409)
        try: self.validate_documents(uid,scope.documents,session=session)
        except AppError:
            raise AppError('KNOWLEDGE_SCOPE_CHANGED','所选资料已更新或删除，请重新准备范围',409) from None
        return scope

    def get_scope(self, uid, sid):
        with self.database.session() as session:
            self.accounts._user(session,uid)
            row = self._scope(session,uid,sid)
            content = ScopeContent.model_validate(row.content['scope'])
            return {'kind':'knowledge_scope','id':row.id,'version':row.version,'goal':row.goal,'input_text':row.goal,
                'documents':deepcopy(row.documents),'supplement':bool(row.supplement),'status':'ready',
                'content':content.model_dump(mode='json'),'evidence':deepcopy(row.content.get('segments',[])),
                'grounding':deepcopy(row.content.get('grounding')),'recommended_candidate_ids':[content.candidates[0].id],
                'created_at':stamp(row.created_at),'expires_at':stamp(row.expires_at)}

    def confirm_scope(self, uid, sid, version, candidate_ids, *, supplement,session=None):
        def confirm(current):
            row = self._scope(current,uid,sid)
            if row.version != version:
                raise AppError('KNOWLEDGE_SCOPE_CHANGED','范围版本已变化，请重新确认',409)
            if bool(row.supplement) != supplement:
                raise AppError('KNOWLEDGE_SCOPE_CHANGED','联网权限已改变，请重新准备并确认范围',409)
            if len(candidate_ids) != len(set(candidate_ids)):
                raise AppError('INVALID_SCOPE_SELECTION','请勿重复选择主题',422)
            try:
                snapshot,points = topic_selection(ScopeContent.model_validate(row.content['scope']),candidate_ids,
                    input_text=row.goal,preparation_id=row.id,version=row.version)
            except ValueError:
                raise AppError('INVALID_SCOPE_SELECTION','请选择本次范围中的学习主题',422) from None
            ids = {sid for point in points for sid in point.evidence_ids}
            return {'scope':snapshot.model_dump(mode='json'),'documents':deepcopy(row.documents),'supplement':bool(row.supplement),
                'segments':[deepcopy(s) for s in row.content.get('segments',[]) if s['id'] in ids],
                'point_evidence':{point.id:point.evidence_ids for point in points},'knowledge_policy':'strict',
                'grounding':deepcopy(row.content.get('grounding')),'material':None}
        if session is not None: return confirm(session)
        with self.database.session() as current:
            self.accounts._user(current,uid)
            return confirm(current)


class ScopePipeline(ScopeRepository):
    def __init__(self, accounts, config, index, *, gateway=None,retriever=None):
        super().__init__(accounts,config)
        self.gateway,self.retriever = gateway,retriever or KnowledgeRetriever(accounts,config,index)

    async def process_async(self, claim):
        old = self.processed_result(claim)
        if old is not None: return old
        payload = claim.payload
        outcome = await self.retriever.retrieve(claim,payload['goal'],payload['documents'],allow_web=payload['supplement'],
            total_model_limit=self.accounts.settings.prepare_model_call_limit,reserve=1)
        if outcome.knowledge_error and outcome.depends_on_documents and not any(s.knowledge for s in outcome.evidence):
            raise AppError(outcome.knowledge_error,'所选资料暂时无法读取，请检查索引后重试',503)
        if not outcome.evidence or outcome.depends_on_documents and not any(s.knowledge for s in outcome.evidence):
            return self.complete(claim,lambda s,j:{'status':'insufficient','reason_code':'INSUFFICIENT_KNOWLEDGE','message':'资料不足以整理可靠学习范围，请补充资料或缩小目标。'})
        saved = await asyncio.to_thread(self.read_checkpoint,claim,'scope-draft')
        valid = {s.id for s in outcome.evidence}
        def check(draft):
            if draft.status == 'ready':
                try:
                    draft.scope.check_evidence(valid)
                    if any(not p.evidence_ids or p.evidence_status != 'available' for c in draft.scope.candidates for f in c.focuses for p in f.points):
                        raise ValueError()
                except ValueError:
                    raise AppError('MODEL_INVALID_OUTPUT','学习范围引用不属于本次实际资料',502) from None
        if saved:
            draft = ScopeDraft.model_validate(saved)
            check(draft)
        else:
            if self.gateway is None and not self.accounts.settings.deepseek_api_key.get_secret_value():
                raise AppError('MODEL_NOT_CONFIGURED','请配置学习模型服务后重试',503)
            async def before(): await self.wait_model_call(claim,self.accounts.settings.prepare_model_call_limit)
            await asyncio.to_thread(self.advance,claim,'summarizing',65)
            gateway = counted_gateway(self.accounts.settings,self.gateway,before,claim.operation_id)
            prompt = ('为原始目标整理待确认学习主题，不出题。只依据实际资料，不用常识猜私有文档；无依据返回 insufficient。'
                '最多3个简明主题候选，按相关性排序，第一个推荐；用户只做一层多选，知识点自动平衡整理。'
                '每个候选最多3个方向、每方向最多6个知识点，所有知识点须有真实 evidence_ids 且 available。'
                '候选描述不超过60字，保留原始目标的比较、机制、应用和版本要求。'
                +UNTRUSTED_DATA_RULE+'\nSchema:'+json.dumps(ScopeDraft.model_json_schema(),ensure_ascii=False)
                +'\n数据:'+json.dumps({'goal':payload['goal'],'evidence':[model_evidence(s) for s in outcome.evidence]},ensure_ascii=False))
            draft = ScopeDraft.model_validate(await gateway.generate(ScopeDraft,prompt,check))
            check(draft)
            await asyncio.to_thread(self.checkpoint,claim,'scope-draft',draft.model_dump(mode='json'),stage='scope_ready',progress=90)
        if draft.status == 'insufficient':
            return self.complete(claim,lambda s,j:{'status':'insufficient','reason_code':'INSUFFICIENT_KNOWLEDGE','message':'当前资料无法支持所需学习范围，请补充资料。'})
        def publish(session,row):
            sid = str(uuid5(NAMESPACE_URL,'levelup-knowledge-scope:'+row.operation_id))
            ids = {sid for c in draft.scope.candidates for f in c.focuses for p in f.points for sid in p.evidence_ids}
            public = [s for s in outcome.evidence if s.id in ids and s.supplement]
            session.add(Scope(id=sid,user_id=row.user_id,operation_id=row.operation_id,goal=row.payload['goal'],
                documents=deepcopy(row.payload['documents']),supplement=int(row.payload['supplement']),created_at=self.now(),
                expires_at=self.now()+timedelta(hours=self.accounts.settings.topic_preparation_ttl_hours),content={
                    'scope':draft.scope.model_dump(mode='json'),'segments':[model_evidence(s) for s in outcome.evidence],
                    'grounding':{'status':'source_backed' if public else 'material_only','provider':'tavily' if public else None,'reason_code':outcome.reason_code}}))
            return {'scope_id':sid}
        return self.complete(claim,publish)

    def process(self, claim): return run_model_job(lambda:self.process_async(claim))
