from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select,func
from app.errors import AppError
from tests.test_knowledge_repository import repo,seed
from tests.test_knowledge_api import knowledge_app
from tests.test_mysql_accounts import system,login


def test_question_input_requires_explicit_scope_and_defaults_network_on():
    from app.knowledge.models import QuestionRequest
    value = QuestionRequest(question='  单轮问题  ',document_ids=['doc'])
    assert value.question=='单轮问题' and value.supplement is True
    for payload in [{'question':'问','document_ids':[]},{'question':'问','document_ids':['doc'],'all_ready':True},
                    {'question':' '*3,'document_ids':['doc']},{'question':'字'*6001,'document_ids':['doc']},
                    {'question':'问','document_ids':['doc'],'history':[{'answer':'secret'}]},
                    {'question':'问','document_ids':['doc','doc']}]:
        with pytest.raises(ValidationError): QuestionRequest.model_validate(payload)
    assert QuestionRequest(question='问',all_ready=True).document_ids==[]


def test_question_submission_is_durable_owned_and_idempotent_without_quiz_or_rewards(repo):
    from app.knowledge.questions import QuestionRepository
    from app.knowledge.database import Usage,Job
    from app.accounts.database import Attempt,User,Quota
    seed(repo)
    questions = QuestionRepository(repo.accounts,repo.config)
    payload = {'question':'按原始资料解释概念','document_ids':['doc']}
    first = questions.submit_question('alice','ask',payload)
    assert questions.submit_question('alice','ask',payload)['id']==first['id']
    assert first['job_type']=='question' and first['status']=='queued'
    with pytest.raises(AppError): questions.submit_question('bob','foreign',payload)
    with pytest.raises(AppError): questions.submit_question('alice','ask',{**payload,'supplement':False})
    with repo.database.session() as session:
        row = session.get(Job,first['id'])
        assert row.payload['documents'][0]['revision_id']=='rev-doc' and row.payload['supplement'] is True
        assert set(row.payload)=={'question','documents','supplement'}
        assert session.scalar(select(Usage)).questions==1
        assert session.scalar(select(func.count()).select_from(Attempt))==0
        assert session.get(User,'alice').xp==0
        assert session.get(Quota,'alice').busy_id is None


def test_question_daily_submission_limit_is_atomic_and_retry_does_not_charge_twice(repo):
    from app.knowledge.questions import QuestionRepository
    seed(repo)
    repo.config.question_daily_limit=1
    questions = QuestionRepository(repo.accounts,repo.config)
    def ask(key):
        try: return questions.submit_question('alice',key,{'question':'问题','all_ready':True})
        except AppError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(ask,['one','two']))
    assert sum(isinstance(value,dict) for value in results)==1
    queued = next(v for v in results if isinstance(v,dict))
    claim = questions.claim('worker')
    questions.model_call(claim,7)
    questions.cancel('alice',queued['id'])
    retried = questions.retry('alice',queued['id'],'retry')
    assert retried['id']!=queued['id']
    questions.model_call(questions.claim('worker'),7)
    from app.knowledge.database import Usage
    with repo.database.session() as session: assert session.scalar(select(Usage)).questions==1


@pytest.mark.anyio
async def test_question_api_creates_short_job_and_rejects_implicit_history(knowledge_app,monkeypatch):
    from app.knowledge.config import KnowledgeSettings
    from app.knowledge.repository import KnowledgeRepository
    monkeypatch.setattr(KnowledgeSettings,'unavailable_reason',lambda self,**kw:None)
    repo = KnowledgeRepository(knowledge_app.state.accounts,knowledge_app.state.knowledge_config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_app),base_url='http://test') as client:
        assert (await client.post('/api/v1/knowledge/questions',json={'question':'问','all_ready':True})).status_code==401
        identity = await login(client)
        seed(repo,uid=identity['user']['id'])
        response = await client.post('/api/v1/knowledge/questions',headers={'Idempotency-Key':'ask'},json={'question':'问','all_ready':True})
        assert response.status_code==200,response.text
        assert response.json()['data']['kind']=='knowledge_job' and response.json()['data']['job_type']=='question'
        assert (await client.post('/api/v1/knowledge/questions',json={'question':'问','all_ready':True,'history':['old']})).status_code==422
