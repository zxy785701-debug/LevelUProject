import httpx
import pytest
from app.knowledge.config import KnowledgeSettings
from app.knowledge.repository import KnowledgeRepository
from tests.test_mysql_accounts import system, login
from tests.test_knowledge_repository import seed


@pytest.fixture
def knowledge_app(system, tmp_path):
    system.state.knowledge_config = KnowledgeSettings(_env_file=None, enabled=True, storage_root=tmp_path/'knowledge',
        embedding_api_key='private-sentinel', embedding_base_url='https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1')
    return system


@pytest.mark.anyio
async def test_capabilities_are_authenticated_sanitized_and_honest(knowledge_app):
    app = knowledge_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        assert (await c.get('/api/v1/knowledge/capabilities')).status_code == 401
        await login(c)
        response = await c.get('/api/v1/knowledge/capabilities')
        assert response.status_code == 200
        result = response.json()['data']
        assert result['enabled'] is True
        assert result['worker']['status'] == 'stopped'
        assert result['formats'] == ['pdf', 'docx', 'md', 'markdown', 'txt', 'web']
        assert 'private-sentinel' not in response.text and str(app.state.knowledge_config.storage_root) not in response.text


@pytest.mark.anyio
async def test_document_read_api_obeys_account_and_pagination(knowledge_app):
    app = knowledge_app
    repo = KnowledgeRepository(app.state.accounts, app.state.knowledge_config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        identity = await login(c)
        seed(repo, uid=identity['user']['id'])
        assert (await c.get('/api/v1/knowledge/documents')).json()['data']['total'] == 1
        assert (await c.get('/api/v1/knowledge/documents/doc')).json()['data']['title'] == '真实资料 doc'
        assert (await c.get('/api/v1/knowledge/documents/doc/chunks')).json()['data']['items'][0]['text'] == 'Original document'
        assert (await c.get('/api/v1/knowledge/documents?page_size=101')).status_code == 422
        await login(c, 'bob')
        assert (await c.get('/api/v1/knowledge/documents')).json()['data']['total'] == 0
        assert (await c.get('/api/v1/knowledge/documents/doc')).status_code == 404
        assert (await c.get('/api/v1/knowledge/documents/doc/chunks')).status_code == 404


@pytest.mark.anyio
async def test_disabled_knowledge_preserves_health_and_core_learning(knowledge_app):
    app = knowledge_app
    app.state.knowledge_config = KnowledgeSettings(_env_file=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        await login(c)
        assert (await c.get('/api/v1/knowledge/capabilities')).json()['data']['reason_code'] == 'KNOWLEDGE_DISABLED'
        assert (await c.get('/api/v1/knowledge/documents')).status_code == 503
        assert (await c.get('/api/v1/health')).status_code == 200
        assert (await c.get('/api/v1/learning')).status_code == 200


@pytest.mark.anyio
async def test_upload_submission_returns_a_job_and_rejects_client_owned_paths(knowledge_app, monkeypatch):
    monkeypatch.setattr(KnowledgeSettings, 'unavailable_reason', lambda self, **kw: None)
    app = knowledge_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        await login(c)
        response = await c.post('/api/v1/knowledge/documents/upload', headers={'Idempotency-Key':'file-key'}, files={'file':('note.md',b'# Notes\nOriginal material','text/markdown')})
        assert response.status_code == 200, response.text
        result = response.json()['data']
        assert result['kind'] == 'knowledge_job' and result['status'] == 'queued' and 'quiz' not in result
        repeated = await c.post('/api/v1/knowledge/documents/upload', headers={'Idempotency-Key':'file-key'}, files={'file':('note.md',b'# Notes\nOriginal material','text/markdown')})
        assert repeated.json()['data']['id'] == result['id']
        invalid = await c.post('/api/v1/knowledge/documents/from-material', json={'material_id':'unknown','user_id':'other','collection':'private'})
        assert invalid.status_code == 422


@pytest.mark.anyio
async def test_web_and_owned_material_submission_api(knowledge_app, monkeypatch):
    from app.accounts.database import Material
    from app.materials.parsers import validate_url
    import app.knowledge.repository as module
    monkeypatch.setattr(KnowledgeSettings, 'unavailable_reason', lambda self, **kw: None)
    monkeypatch.setattr(module, 'validate_url', lambda url: validate_url(url, resolve=lambda _: ['93.184.216.34']))
    app = knowledge_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        identity = await login(c)
        response = await c.post('/api/v1/knowledge/documents/web', json={'url':'https://example.org/page'})
        assert response.status_code == 200 and response.json()['data']['status'] == 'queued'
        with app.state.accounts.database.session() as s:
            s.add(Material(id='material',user_id=identity['user']['id'],content={'title':'旧材料','source_type':'txt','segments':[{'id':'s1','text':'原文'}]}))
        copied = await c.post('/api/v1/knowledge/documents/from-material', json={'material_id':'material'})
        assert copied.status_code == 200 and copied.json()['data']['document_id']
        await login(c,'other')
        assert (await c.post('/api/v1/knowledge/documents/from-material', json={'material_id':'material'})).status_code == 404


@pytest.mark.anyio
async def test_job_query_cancel_retry_and_foreign_account_are_isolated(knowledge_app, monkeypatch):
    monkeypatch.setattr(KnowledgeSettings, 'unavailable_reason', lambda self, **kw: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_app), base_url='http://test') as c:
        await login(c)
        job = (await c.post('/api/v1/knowledge/documents/upload',files={'file':('note.txt',b'Notes')})).json()['data']
        path = '/api/v1/knowledge/jobs/'+job['id']
        assert (await c.get(path)).json()['data']['status'] == 'queued'
        assert (await c.post(path+'/cancel')).json()['data']['status'] == 'cancelled'
        retried = await c.post(path+'/retry',headers={'Idempotency-Key':'retry'})
        assert retried.status_code == 200 and retried.json()['data']['status'] == 'queued'
        assert (await c.post(path+'/retry',headers={'Idempotency-Key':'retry'})).json()['data']['id'] == retried.json()['data']['id']
        await login(c,'foreign')
        for suffix,method in [('',c.get),('/cancel',c.post),('/retry',c.post)]:
            assert (await method(path+suffix)).status_code == 404


@pytest.mark.anyio
async def test_reindex_and_delete_api_are_owned_and_delete_remains_available_when_disabled(knowledge_app,monkeypatch):
    monkeypatch.setattr(KnowledgeSettings,'unavailable_reason',lambda self,**kw:None)
    repo = KnowledgeRepository(knowledge_app.state.accounts,knowledge_app.state.knowledge_config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_app),base_url='http://test') as client:
        identity = await login(client)
        seed(repo,uid=identity['user']['id'])
        response = await client.post('/api/v1/knowledge/documents/doc/reindex',headers={'Idempotency-Key':'reindex'})
        assert response.status_code == 200, response.text
        assert response.json()['data']['job_type'] == 'reindex'
        await login(client,'other')
        assert (await client.post('/api/v1/knowledge/documents/doc/reindex')).status_code == 404
        assert (await client.delete('/api/v1/knowledge/documents/doc')).status_code == 404
        await login(client)
        knowledge_app.state.knowledge_config.enabled = False
        assert (await client.delete('/api/v1/knowledge/documents/doc')).json()['data']['deleted'] is True
        assert (await client.delete('/api/v1/knowledge/documents/doc')).status_code == 200
