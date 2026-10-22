import httpx
import pytest
from tests.test_knowledge_api import knowledge_app
from tests.test_mysql_accounts import system,login


@pytest.mark.anyio
async def test_material_choices_and_key_lookup_are_owned_and_hide_private_payloads(knowledge_app,monkeypatch):
    from app.accounts.database import Material
    from app.knowledge.config import KnowledgeSettings
    monkeypatch.setattr(KnowledgeSettings,'unavailable_reason',lambda self,**kw:None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_app),base_url='http://test') as client:
        identity = await login(client)
        uid = identity['user']['id']
        with knowledge_app.state.accounts.database.session() as session:
            for kind in ('txt','web','video'):
                session.add(Material(id=kind,user_id=uid,content={'title':'原材料'+kind,'source_type':kind,'segments':[{'id':'s','text':'private original text'}]}))
        response = await client.get('/api/v1/knowledge/materials')
        assert response.status_code==200,response.text
        assert {m['id'] for m in response.json()['data']['items']}=={'txt','web'}
        assert 'private original text' not in response.text
        queued = (await client.post('/api/v1/knowledge/documents/upload',headers={'Idempotency-Key':'lost-response'},files={'file':('a.txt',b'actual body')})).json()['data']
        restored = await client.get('/api/v1/knowledge/job-lookup?job_type=import&key=lost-response')
        assert restored.status_code==200 and restored.json()['data']['id']==queued['id']
        assert 'actual body' not in restored.text and 'file_path' not in restored.text
        await login(client,'other')
        assert (await client.get('/api/v1/knowledge/materials')).json()['data']['items']==[]
        assert (await client.get('/api/v1/knowledge/job-lookup?job_type=import&key=lost-response')).status_code==404


@pytest.mark.anyio
async def test_delete_returns_real_durable_cleanup_identity_and_owned_status(knowledge_app,monkeypatch):
    from app.knowledge.config import KnowledgeSettings
    monkeypatch.setattr(KnowledgeSettings,'unavailable_reason',lambda self,**kw:None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_app),base_url='http://test') as client:
        await login(client)
        queued = (await client.post('/api/v1/knowledge/documents/upload',files={'file':('a.txt',b'actual body')})).json()['data']
        response = await client.delete('/api/v1/knowledge/documents/'+queued['document_id'])
        cleanup = response.json()['data']['cleanup']
        assert cleanup['kind']=='knowledge_cleanup' and cleanup['status']=='queued'
        assert (await client.delete('/api/v1/knowledge/documents/'+queued['document_id'])).json()['data']['cleanup']['id']==cleanup['id']
        status = await client.get('/api/v1/knowledge/cleanup/'+cleanup['id'])
        assert status.status_code==200 and status.json()['data']['status']=='queued'
        assert 'file_path' not in status.text
        await login(client,'other')
        assert (await client.get('/api/v1/knowledge/cleanup/'+cleanup['id'])).status_code==404
