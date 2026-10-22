import asyncio
import json
import math
from copy import deepcopy
import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import select
from app.errors import AppError
from tests.knowledge_support import embedding_response
from tests.test_knowledge_repository import repo
from tests.test_knowledge_jobs import submit


@pytest.fixture
def embedding(repo):
    from app.knowledge.embeddings import BailianEmbeddings
    from app.knowledge.budgets import JobBudgets
    repo.config.enabled = True
    repo.config.embedding_api_key = SecretStr('fake-independent-bailian-key')
    repo.config.embedding_base_url = 'https://test-space.cn-beijing.maas.aliyuncs.com/api/v1'
    submit(repo)
    jobs = JobBudgets(repo.accounts,repo.config)
    claim = jobs.claim('worker')
    state = {'calls':[],'statuses':[],'mutate':None,'delays':[]}
    def handler(request):
        state['calls'].append(request)
        status = state['statuses'].pop(0) if state['statuses'] else 200
        if status == 'timeout': raise httpx.ReadTimeout('private provider details',request=request)
        if status != 200: return httpx.Response(status,json={'message':'secret provider details'},headers={'Retry-After':'0'})
        response = embedding_response(request)
        if state['mutate']:
            body = response.json()
            state['mutate'](body)
            response = httpx.Response(200,json=body)
        return response
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = BailianEmbeddings(repo.accounts,repo.config,claim,client=client,sleep=state['delays'].append)
    yield adapter,state,jobs,claim
    client.close()


def test_native_contract_batching_order_query_async_and_independent_credentials(embedding):
    from langchain_core.embeddings import Embeddings
    adapter,state,_,_ = embedding
    assert isinstance(adapter,Embeddings)
    state['mutate'] = lambda body: body['output']['embeddings'].reverse()
    texts = ['中文片段'+str(n) for n in range(12)]
    vectors = adapter.embed_documents(texts)
    assert len(vectors) == 12 and all(len(v)==1024 for v in vectors)
    assert len(state['calls']) == 2
    assert [len(json.loads(r.content)['input']['texts']) for r in state['calls']] == [10,2]
    request = state['calls'][0]
    assert str(request.url) == 'https://test-space.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding'
    assert request.headers['Authorization'] == 'Bearer fake-independent-bailian-key'
    body = json.loads(request.content)
    assert body['model'] == 'text-embedding-v4'
    assert body['parameters'] == {'dimension':1024,'text_type':'document'}
    expected = embedding_response(httpx.Request('POST','https://fake',json={'input':{'texts':texts}})).json()['output']['embeddings']
    assert vectors == [r['embedding'] for r in expected]
    query = asyncio.run(adapter.aembed_query('检索问题'))
    assert len(query) == 1024
    assert json.loads(state['calls'][-1].content)['parameters']['text_type'] == 'query'
    # MySQL JSON numeric round trips can differ by one floating point ULP.
    assert all(actual == pytest.approx(expected,rel=1e-12) for actual,expected in zip(asyncio.run(adapter.aembed_documents(texts)),vectors,strict=True))
    assert len(state['calls']) == 3


@pytest.mark.parametrize('case',['count','duplicate','index','dimension','nan','boolean'])
def test_malformed_vectors_cannot_be_cached_or_published(embedding,case):
    adapter,state,_,_ = embedding
    def mutate(body):
        rows = body['output']['embeddings']
        if case == 'count': rows.clear()
        elif case == 'duplicate': rows.append(deepcopy(rows[0]))
        elif case == 'index': rows[0]['text_index'] = 3
        elif case == 'dimension': rows[0]['embedding'].pop()
        elif case == 'nan': rows[0]['embedding'][0] = 'NaN'
        else: rows[0]['embedding'][0] = True
    state['mutate'] = mutate
    with pytest.raises(AppError) as error: adapter.embed_documents(['实际正文'])
    assert error.value.code == 'EMBEDDING_INVALID_RESPONSE'
    assert len(state['calls']) == 1


@pytest.mark.parametrize('statuses,attempts,success',[
    ([429,200],2,True),(['timeout',200],2,True),([500,502,503],3,False),
    ([401],1,False),([402],1,False),([403],1,False),([400],1,False),
])
def test_bounded_transient_retries_and_no_auth_balance_retry(embedding,statuses,attempts,success):
    adapter,state,jobs,claim = embedding
    state['statuses'] = statuses[:]
    if success: assert len(adapter.embed_query('问题')) == 1024
    else:
        with pytest.raises(AppError) as error: adapter.embed_query('问题')
        assert 'private' not in error.value.message and 'secret' not in error.value.message
    assert len(state['calls']) == attempts
    from app.knowledge.database import Usage
    with jobs.database.session() as session:
        usage = session.scalar(select(Usage))
        assert usage.embedding_actual+usage.embedding_reserved == len('问题'.encode())*attempts


def test_cache_is_owned_profile_specific_deduplicated_and_independent_of_query_type(embedding,repo):
    from app.knowledge.embeddings import BailianEmbeddings
    from app.knowledge.budgets import JobBudgets
    adapter,state,_,claim = embedding
    assert adapter.embed_documents(['same','same'])[0] == pytest.approx(adapter.embed_documents(['same'])[0],rel=1e-12)
    assert len(state['calls']) == 1
    adapter.embed_query('same')
    assert len(state['calls']) == 2
    with repo.database.session() as session:
        from app.knowledge.database import Job
        row = session.get(Job,claim.id)
        row.status,row.owner,row.lease_until = 'succeeded',None,None
    other = repo.submit_file('bob','bob','b.txt',b'content')
    claim = JobBudgets(repo.accounts,repo.config).claim('worker')
    another = BailianEmbeddings(repo.accounts,repo.config,claim,client=adapter.client,sleep=lambda _:None)
    another.embed_documents(['same'])
    assert len(state['calls']) == 3
    repo.config.embedding_base_url = 'https://other.cn-beijing.maas.aliyuncs.com/api/v1'
    changed = BailianEmbeddings(repo.accounts,repo.config,claim,client=adapter.client,sleep=lambda _:None)
    changed.embed_documents(['same'])
    assert len(state['calls']) == 4


def test_input_upper_bounds_fail_before_paid_request_and_safe_parts_preserve_text(embedding):
    from app.knowledge.embeddings import safe_text_parts
    adapter,state,_,_ = embedding
    for texts in ([''],['中文'*5000],['a',True]):
        with pytest.raises(AppError): adapter.embed_documents(texts)
    assert not state['calls'] and adapter.embed_documents([]) == []
    text = '中文😀'*3000
    parts = safe_text_parts(text)
    assert ''.join(parts) == text and all(len(p.encode())<=8192 for p in parts)


def test_budget_exhaustion_response_loss_and_cancelled_response_are_accounted(embedding,repo):
    adapter,state,jobs,claim = embedding
    repo.config.embedding_daily_tokens = 10
    state['statuses'] = ['timeout',200]
    with pytest.raises(AppError) as error: adapter.embed_query('中文')
    assert error.value.code == 'KNOWLEDGE_EMBEDDING_DAILY_LIMIT' and len(state['calls']) == 1
    repo.config.embedding_daily_tokens = 1000
    state['statuses'] = []
    def cancel(body): jobs.cancel('alice',claim.id)
    state['mutate'] = cancel
    with pytest.raises(AppError): adapter.embed_query('新问题')
    from app.knowledge.database import Usage,EmbeddingCache
    with jobs.database.session() as session:
        usage = session.scalar(select(Usage))
        assert usage.embedding_reserved == len('中文'.encode())
        assert usage.embedding_actual == len('新问题'.encode())
        assert session.scalar(select(EmbeddingCache)) is None
