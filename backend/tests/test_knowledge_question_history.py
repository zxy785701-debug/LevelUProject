import asyncio
from copy import deepcopy
import httpx
import pytest
from sqlalchemy import select,func,event
from sqlalchemy.orm import Session
from app.errors import AppError
from tests.test_knowledge_repository import repo,seed
from tests.test_knowledge_index import index
from tests.test_knowledge_retrieval_store import ready
from tests.test_knowledge_answering import draft,review
from tests.test_grounding_generation import SequenceGateway
from tests.test_knowledge_api import knowledge_app
from tests.test_mysql_accounts import system,login


def setup_question(repo,index):
    from app.knowledge.question_pipeline import QuestionPipeline
    from app.knowledge.retrieval_store import KnowledgeRetriever
    selected = ready(repo,index)
    class Embeddings:
        async def aembed_query(self,text): return [1.0]*1024
    source_id = 'kb-'+repo.chunks('alice',selected[0]['id'])['items'][0]['id']
    gateway = SequenceGateway([draft([source_id]),review(ids=[source_id])])
    pipeline = QuestionPipeline(repo.accounts,repo.config,index,gateway=gateway,
        retriever=KnowledgeRetriever(repo.accounts,repo.config,index,embedding_factory=lambda claim:Embeddings()))
    row = pipeline.submit_question('alice','question',{'question':'按原始资料解释','document_ids':[selected[0]['id']],'supplement':False})
    return pipeline,pipeline.claim('worker'),gateway,selected,row


def test_full_question_publication_creates_history_but_no_learning_attempt_or_reward(index,repo):
    from app.knowledge.database import Question,Usage
    from app.accounts.database import Attempt,Reward,User,Quota
    pipeline,claim,gateway,selected,row = setup_question(repo,index)
    result = pipeline.process(claim)
    detail = pipeline.question('alice',result['question_id'])
    assert detail['kind']=='knowledge_answer' and detail['status']=='answered'
    assert detail['question']=='按原始资料解释' and detail['sources'][0]['knowledge']['document_id']==selected[0]['id']
    assert pipeline.get('alice',row['id'])['status']=='succeeded'
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Question))==1
        assert session.scalar(select(func.count()).select_from(Attempt))==0
        assert session.scalar(select(func.count()).select_from(Reward))==0
        assert session.get(User,'alice').xp==session.get(User,'alice').coins==0
        assert session.get(Quota,'alice').quiz_count==0
        assert session.scalar(select(Usage)).questions==1
    assert len(gateway.calls)==2


def test_publish_commit_failure_restores_without_new_model_calls_or_duplicate_history(index,repo):
    from app.knowledge.database import Question,Job
    pipeline,claim,gateway,selected,row = setup_question(repo,index)
    def fail(session):
        # The just-flushed Question has no strong reference; the in-flight Job
        # remains attached until the final transaction exits.
        if any(isinstance(obj,Job) and obj.kind=='question' and obj.status=='succeeded' for obj in session.identity_map.values()):
            raise RuntimeError('publish commit interruption')
    event.listen(Session,'before_commit',fail)
    try:
        with pytest.raises(RuntimeError): pipeline.process(claim)
    finally: event.remove(Session,'before_commit',fail)
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Question))==0
        assert session.get(Job,row['id']).status=='running'
    pipeline.fail(claim,'INTERRUPTED','恢复',recoverable=True)
    resumed = pipeline.claim('new-worker')
    pipeline.gateway = SequenceGateway([])
    result = pipeline.process(resumed)
    assert pipeline.processed_result(resumed)==result
    with repo.database.session() as session: assert session.scalar(select(func.count()).select_from(Question))==1


def test_history_and_quiz_context_use_original_goal_and_version_not_ai_answer(index,repo):
    from app.knowledge.cleanup import LibraryManagement
    pipeline,claim,gateway,selected,row = setup_question(repo,index)
    qid = pipeline.process(claim)['question_id']
    context = pipeline.quiz_context('alice',qid)
    assert context['goal']=='按原始资料解释' and context['requires_confirmation'] is True
    assert '实际资料支持的回答' not in str(context)
    from app.knowledge.database import Document,Revision
    with repo.database.session() as session:
        session.add(Revision(id='changed-revision',document_id=selected[0]['id'],number=2,profile=pipeline.profile,status='ready',text='更新后的原文'))
        session.flush()
        session.get(Document,selected[0]['id']).active_revision_id='changed-revision'
    assert pipeline.question('alice',qid)['sources'][0]['knowledge']['version_changed'] is True
    with pytest.raises(AppError): pipeline.quiz_context('alice',qid)
    LibraryManagement(repo.accounts,repo.config).delete_document('alice',selected[0]['id'])
    detail = pipeline.question('alice',qid)
    assert detail['sources'][0]['knowledge']['deleted'] is True
    with pytest.raises(AppError): pipeline.quiz_context('alice',qid)
    assert pipeline.list_questions('alice')['total']==1 and pipeline.list_questions('bob')['total']==0
    with pytest.raises(AppError): pipeline.question('bob',qid)
    pipeline.delete_question('alice',qid)
    pipeline.delete_question('alice',qid)
    with pytest.raises(AppError): pipeline.question('alice',qid)
    assert pipeline.list_questions('alice')['total']==0
    from app.knowledge.database import Checkpoint
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Checkpoint).where(Checkpoint.operation_id==claim.operation_id))==0


@pytest.mark.anyio
async def test_history_api_is_owned_and_available_when_new_entry_is_disabled(knowledge_app):
    from app.knowledge.questions import QuestionRepository
    from app.knowledge.database import Question
    from uuid import uuid4
    repo = QuestionRepository(knowledge_app.state.accounts,knowledge_app.state.knowledge_config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_app),base_url='http://test') as client:
        identity = await login(client)
        uid = identity['user']['id']
        seed(repo,uid=uid)
        qid = str(uuid4())
        with repo.database.session() as session:
            session.add(Question(id=qid,user_id=uid,operation_id=str(uuid4()),question='原始问题',documents=repo.select_documents(uid,['doc']),supplement=1,
                content={'status':'insufficient','paragraphs':[],'sources':[],'grounding':None,'conflicts':[],'reason_code':'INSUFFICIENT_KNOWLEDGE','message':'资料不足','network':{'requested':True,'status':'skipped','reason_code':None}}))
        knowledge_app.state.knowledge_config.enabled=False
        response = await client.get('/api/v1/knowledge/questions/'+qid)
        assert response.status_code==200,response.text
        assert (await client.get('/api/v1/knowledge/questions')).json()['data']['total']==1
        assert (await client.get('/api/v1/knowledge/questions/'+qid+'/quiz-context')).json()['data']['goal']=='原始问题'
        await login(client,'other')
        assert (await client.get('/api/v1/knowledge/questions/'+qid)).status_code==404
        assert (await client.delete('/api/v1/knowledge/questions/'+qid)).status_code==404
        await login(client)
        assert (await client.delete('/api/v1/knowledge/questions/'+qid)).status_code==200
        assert (await client.get('/api/v1/knowledge/questions/'+qid)).status_code==404
