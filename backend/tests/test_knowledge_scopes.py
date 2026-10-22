from datetime import timedelta
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select,func
from app.errors import AppError
from tests.test_knowledge_repository import repo,seed
from tests.test_knowledge_index import index
from tests.test_knowledge_retrieval_store import ready
from tests.test_grounding_generation import SequenceGateway
from tests.test_knowledge_api import knowledge_app
from tests.test_mysql_accounts import system,login


def scope_content(source_id):
    return {'candidates':[{'id':'topic-'+str(i),'topic':'主题'+str(i),'domain':'资料学习','description':'直接回应原始目标',
        'focuses':[{'id':'focus-'+str(i),'name':'机制与应用','description':'从原文学习',
            'points':[{'id':'point-'+str(i),'name':'知识点'+str(i),'evidence_ids':[source_id],'evidence_status':'available'}]}]} for i in range(2)]}


def setup_scope(repo,index):
    from app.knowledge.scopes import ScopePipeline
    from app.knowledge.retrieval_store import KnowledgeRetriever
    selected = ready(repo,index)
    class Embeddings:
        async def aembed_query(self,text): return [1.0]*1024
    sid = 'kb-'+repo.chunks('alice',selected[0]['id'])['items'][0]['id']
    gateway = SequenceGateway([{'status':'ready','scope':scope_content(sid)}])
    pipeline = ScopePipeline(repo.accounts,repo.config,index,gateway=gateway,
        retriever=KnowledgeRetriever(repo.accounts,repo.config,index,embedding_factory=lambda claim:Embeddings()))
    body = {'goal':'根据资料比较机制及应用','document_ids':[selected[0]['id']],'supplement':False}
    queued = pipeline.submit_preparation('alice','prepare',body)
    return pipeline,pipeline.claim('worker'),gateway,selected,queued,body


def test_scope_submission_is_durable_explicit_and_does_not_reserve_core_busy(repo):
    from app.knowledge.scopes import ScopeRepository
    from app.knowledge.models import ScopeRequest
    from app.accounts.database import Quota
    seed(repo)
    scopes = ScopeRepository(repo.accounts,repo.config)
    payload = ScopeRequest(goal='学习原始目标',all_ready=True)
    assert payload.supplement is True
    row = scopes.submit_preparation('alice','prepare',payload)
    assert scopes.submit_preparation('alice','prepare',payload)['id']==row['id']
    with repo.database.session() as session:
        quota = session.get(Quota,'alice')
        assert quota.busy_id is None and quota.topic_prepare_count==1 and quota.quiz_count==0


def test_prepared_scope_has_one_level_recommended_multi_topic_confirmation(index,repo):
    from app.accounts.database import Attempt,Quota
    pipeline,claim,gateway,selected,queued,body = setup_scope(repo,index)
    result = pipeline.process(claim)
    prepared = pipeline.get_scope('alice',result['scope_id'])
    assert prepared['goal']==body['goal'] and prepared['recommended_candidate_ids']==['topic-0']
    assert len(prepared['content']['candidates'])==2
    context = pipeline.confirm_scope('alice',prepared['id'],1,['topic-0','topic-1'],supplement=False)
    assert len(context['scope']['selected_topics'])==2 and context['scope']['input_text']==body['goal']
    assert context['knowledge_policy']=='strict' and context['documents']==selected
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Attempt))==0
        assert session.get(Quota,'alice').topic_prepare_count==1
    assert len(gateway.calls)==1


def test_scope_rejects_wrong_owner_version_permission_selection_and_changed_documents(index,repo):
    from app.knowledge.cleanup import LibraryManagement
    pipeline,claim,gateway,selected,queued,body = setup_scope(repo,index)
    sid = pipeline.process(claim)['scope_id']
    for uid,version,ids,supplement in [('bob',1,['topic-0'],False),('alice',2,['topic-0'],False),
        ('alice',1,[],False),('alice',1,['foreign'],False),('alice',1,['topic-0'],True)]:
        with pytest.raises(AppError): pipeline.confirm_scope(uid,sid,version,ids,supplement=supplement)
    LibraryManagement(repo.accounts,repo.config).delete_document('alice',selected[0]['id'])
    with pytest.raises(AppError): pipeline.get_scope('alice',sid)


def test_scope_cannot_fabricate_evidence_and_insufficient_result_is_explicit(index,repo):
    from app.knowledge.database import Scope
    pipeline,claim,gateway,selected,queued,body = setup_scope(repo,index)
    gateway.responses = [{'status':'ready','scope':scope_content('invented-source')}]
    with pytest.raises(AppError): pipeline.process(claim)
    with repo.database.session() as session: assert session.scalar(select(func.count()).select_from(Scope))==0
    pipeline.gateway = SequenceGateway([{'status':'insufficient','reason':'真实资料不足'}])
    value = pipeline.process(claim)
    assert value['status']=='insufficient' and value['reason_code']=='INSUFFICIENT_KNOWLEDGE'


@pytest.mark.anyio
async def test_scope_prepare_api_returns_job_and_get_is_owned(knowledge_app,monkeypatch):
    from app.knowledge.config import KnowledgeSettings
    from app.knowledge.scopes import ScopeRepository
    from app.knowledge.database import Scope
    monkeypatch.setattr(KnowledgeSettings,'unavailable_reason',lambda self,**kw:None)
    scopes = ScopeRepository(knowledge_app.state.accounts,knowledge_app.state.knowledge_config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_app),base_url='http://test') as client:
        identity = await login(client)
        uid = identity['user']['id']
        seed(scopes,uid=uid)
        queued = await client.post('/api/v1/knowledge/quiz-preparations',json={'goal':'学习资料','all_ready':True})
        assert queued.status_code==200,queued.text
        assert queued.json()['data']['job_type']=='prepare'
        sid = str(uuid4())
        with scopes.database.session() as session:
            session.add(Scope(id=sid,user_id=uid,operation_id=str(uuid4()),goal='学习资料',documents=scopes.select_documents(uid,['doc']),
                supplement=1,content={'scope':scope_content('s1'),'segments':[],'grounding':{'status':'material_only'}},expires_at=scopes.now()+timedelta(hours=24)))
        assert (await client.get('/api/v1/knowledge/quiz-preparations/'+sid)).status_code==200
        await login(client,'other')
        assert (await client.get('/api/v1/knowledge/quiz-preparations/'+sid)).status_code==404
