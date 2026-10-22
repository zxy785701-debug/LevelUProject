import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.errors import AppError
from app.knowledge.database import Job,Scope,Checkpoint,Revision,Document
from app.accounts.database import Quota
from app.knowledge.scopes import ScopeRepository,ScopePipeline,ScopeDraft
from app.knowledge.quizzes import QuizPipeline,CheckpointGateway
from app.knowledge.retrieval import KnowledgeOutcome
from app.quiz_grounding.models import QuizDraftResult
from app.quiz_grounding.generation import DRAFT_VERSION,REVIEW_VERSION
from tests.test_knowledge_repository import repo,seed
from tests.test_knowledge_index import index,staged
from tests.test_knowledge_scopes import setup_scope,scope_content
from tests.test_knowledge_quiz_publication import setup_quiz
from tests.test_grounding_generation import SequenceGateway,review
from tests.helpers import quiz_payload
from tests.test_knowledge_boundaries import fails


def test_preparation_quota_identity_and_scope_draft_consistency(repo):
    from pydantic import ValidationError
    seed(repo); scopes=ScopeRepository(repo.accounts,repo.config)
    body={'goal':'原目标','document_ids':['doc']}
    fails('INVALID_INPUT',lambda:scopes.submit_preparation('alice','',body))
    scopes.submit_preparation('alice','prepare',body)
    fails('IDEMPOTENCY_CONFLICT',lambda:scopes.submit_preparation('alice','prepare',{**body,'supplement':False}))
    with repo.database.session() as session: session.get(Quota,'alice').topic_prepare_count=repo.accounts.settings.topic_prepare_daily_limit
    fails('TOPIC_PREPARE_DAILY_LIMIT',lambda:scopes.submit_preparation('alice','other',body))
    with pytest.raises(ValidationError): ScopeDraft(status='ready')


def test_completed_scope_replays_without_model_and_rejects_expiry_and_duplicate_topics(index,repo):
    pipeline,claim,gateway,selected,queued,body=setup_scope(repo,index)
    result=pipeline.process(claim)
    assert pipeline.process(claim)==result and len(gateway.calls)==1
    fails('INVALID_SCOPE_SELECTION',lambda:pipeline.confirm_scope('alice',result['scope_id'],1,['topic-0','topic-0'],supplement=False))
    with repo.database.session() as session: session.get(Scope,result['scope_id']).expires_at=repo.now()-timedelta(seconds=1)
    fails('KNOWLEDGE_SCOPE_EXPIRED',lambda:pipeline.get_scope('alice',result['scope_id']))


@pytest.mark.parametrize('case',['index_error','empty','public_only','unverified','no_model'])
def test_scope_never_guesses_private_learning_topics(index,repo,case):
    pipeline,claim,gateway,selected,queued,body=setup_scope(repo,index)
    class Retriever:
        async def retrieve(self,*a,**kw):
            if case=='index_error': return KnowledgeOutcome(knowledge_error='KNOWLEDGE_INDEX_UNAVAILABLE')
            if case in ('empty','public_only'): return KnowledgeOutcome(evidence=[])
            return await pipeline_original.retrieve(*a,**kw)
    pipeline_original=pipeline.retriever
    pipeline.retriever=Retriever()
    if case=='index_error': fails('KNOWLEDGE_INDEX_UNAVAILABLE',lambda:pipeline.process(claim))
    elif case in ('empty','public_only'): assert pipeline.process(claim)['status']=='insufficient'
    elif case=='no_model':
        pipeline.gateway=None
        from pydantic import SecretStr
        repo.accounts.settings.deepseek_api_key=SecretStr('')
        fails('MODEL_NOT_CONFIGURED',lambda:pipeline.process(claim))
    else:
        evidence=asyncio.run(pipeline_original.retrieve(claim,body['goal'],selected,allow_web=False)).evidence
        content=scope_content(evidence[0].id)
        content['candidates'][0]['focuses'][0]['points'][0]['evidence_status']='unverified'
        pipeline.gateway=SequenceGateway([{'status':'ready','scope':content}])
        fails('MODEL_INVALID_OUTPUT',lambda:pipeline.process(claim))


def test_scope_checkpoint_restores_draft_without_paid_regeneration(index,repo):
    pipeline,claim,gateway,selected,queued,body=setup_scope(repo,index)
    sid='kb-'+repo.chunks('alice',selected[0]['id'])['items'][0]['id']
    pipeline.checkpoint(claim,'scope-draft',{'status':'ready','scope':scope_content(sid)},stage='scope_ready',progress=90)
    pipeline.gateway=SequenceGateway([])
    assert pipeline.process(claim)['scope_id']


def test_quiz_idempotency_key_quota_and_validated_policy_guards(index,repo):
    pipeline,claim,gateway,queued,body=setup_quiz(repo,index)
    fails('INVALID_INPUT',lambda:pipeline.submit_quiz('alice','',body))
    fails('IDEMPOTENCY_CONFLICT',lambda:pipeline.submit_quiz('alice','quiz',{**body,'question_count':5}))
    with repo.database.session() as session: session.get(Quota,'alice').quiz_count=repo.accounts.settings.quiz_daily_limit
    fails('DAILY_QUOTA_EXCEEDED',lambda:pipeline.submit_quiz('alice','new',body))
    pipeline.checkpoint(claim,'validated-quiz',{'draft_version':'old','review_version':REVIEW_VERSION,'quiz':{}},stage='publishing',progress=90)
    fails('KNOWLEDGE_CHECKPOINT_CHANGED',lambda:pipeline.process(claim))


def test_quiz_checkpoints_validate_prompt_and_reuse_unspent_call_credit(index,repo):
    pipeline,claim,gateway,queued,body=setup_quiz(repo,index)
    async def exercise():
        checked=[]
        first=CheckpointGateway(pipeline,claim,SequenceGateway([{'status':'ready','quiz':quiz_payload()}]))
        before=first.remaining()
        await first.generate(QuizDraftResult,'identical prompt',lambda v:checked.append(v.status))
        restored=CheckpointGateway(pipeline,claim,SequenceGateway([]))
        assert restored.remaining()==before+1
        checks_before_restore=len(checked)
        result=await restored.generate(QuizDraftResult,'identical prompt',lambda v:checked.append(v.status))
        assert result.status=='ready' and checked==['ready']*(checks_before_restore+1)
        changed=CheckpointGateway(pipeline,claim,SequenceGateway([]))
        with pytest.raises(AppError) as caught: await changed.generate(QuizDraftResult,'changed prompt')
        assert caught.value.code=='KNOWLEDGE_CHECKPOINT_CHANGED'
    asyncio.run(exercise())


@pytest.mark.parametrize('case',['index_error','refresh','no_model'])
def test_stale_online_quiz_refreshes_sources_and_cannot_reuse_old_web(index,repo,case):
    from pydantic import SecretStr
    pipeline,claim,gateway,queued,body=setup_quiz(repo,index)
    with repo.database.session() as session:
        row=session.get(Job,claim.id); payload=deepcopy(row.payload)
        payload['selection']['supplement']=True
        payload['context']['prepared_at']=(repo.now()-timedelta(hours=1)).isoformat()
        payload['context']['supplement']=True
        row.payload=payload
        session.get(Scope,body['scope_id']).supplement=1
    from dataclasses import replace
    claim=replace(claim,payload=payload)
    class Retriever:
        async def retrieve(self,*a,**kw):
            assert kw['allow_web'] is True
            if case=='index_error': return KnowledgeOutcome(knowledge_error='KNOWLEDGE_INDEX_UNAVAILABLE')
            from app.quiz_grounding.snapshots import EvidenceSegment
            return KnowledgeOutcome(evidence=[EvidenceSegment.model_validate(s) for s in payload['context']['segments']],reason_code='SUPPLEMENT_FAILED')
    pipeline.retriever=Retriever()
    if case=='index_error': fails('KNOWLEDGE_INDEX_UNAVAILABLE',lambda:pipeline.process(claim))
    elif case=='no_model':
        pipeline.gateway=None; repo.accounts.settings.deepseek_api_key=SecretStr('')
        fails('MODEL_NOT_CONFIGURED',lambda:pipeline.process(claim))
    else:
        result=pipeline.process(claim)
        assert result['quiz']['grounding']['status']=='material_only'
        assert result['quiz']['grounding']['reason_code']=='SUPPLEMENT_FAILED'


def test_reindex_rejects_unready_wrong_identity_active_work_and_import_quota(index,repo):
    from app.knowledge.indexing import ImportIndexer
    pipeline=ImportIndexer(repo.accounts,repo.config,index)
    seed(repo,ready=False)
    fails('INVALID_INPUT',lambda:pipeline.submit_reindex('alice','','doc'))
    fails('DOCUMENT_NOT_READY',lambda:pipeline.submit_reindex('alice','reindex','doc'))
    with repo.database.session() as session:
        session.get(Document,'doc').status='ready'; session.get(Document,'doc').active_revision_id='rev-doc'
        session.get(Revision,'rev-doc').status='ready'
    first=pipeline.submit_reindex('alice','reindex','doc')
    assert pipeline.submit_reindex('alice','other','doc')['id']==first['id']
    seed(repo,did='other')
    fails('IDEMPOTENCY_CONFLICT',lambda:pipeline.submit_reindex('alice','reindex','other'))
    pipeline.cancel('alice',first['id']); repo.config.import_daily_limit=1
    fails('KNOWLEDGE_IMPORT_DAILY_LIMIT',lambda:pipeline.submit_reindex('alice','quota','other'))
