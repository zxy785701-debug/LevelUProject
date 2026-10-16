import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.accounts.database import Quota
from tests.test_mysql_accounts import system, login
from tests.test_multisource_accounts import FeatureGateway, upload
from tests.test_grounding_tavily import wire


@pytest.mark.anyio
async def test_material_capability_uses_tavily_and_supplement_false_never_searches(system):
    system.state.settings.tavily_api_key = SecretStr('test-only')
    system.state.settings.jina_api_key = SecretStr('')
    system.state.gateway = FeatureGateway()
    async def unexpected_search(*args):
        raise AssertionError('Supplement disabled must not search')
    system.state.sources.search = unexpected_search
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        material = await upload(c)
        assert material['search_available'] is True
        result = await c.post('/api/v1/quiz/generate', json={'material_id': material['id'], 'question_count': 3, 'supplement': False})
        assert result.status_code == 200, result.text
        system.state.settings.tavily_api_key = SecretStr('')
        system.state.settings.jina_api_key = SecretStr('legacy-only')
        assert (await c.get('/api/v1/materials/' + material['id'])).json()['data']['search_available'] is False


@pytest.mark.anyio
async def test_account_busy_is_checked_before_paid_web_extract(system, monkeypatch):
    from app.materials.api import process_material, LinkBody
    calls = []
    async def extract(url, **kwargs):
        calls.append(url)
        raise AssertionError('No paid read when busy')
    system.state.sources.web = extract
    accounts = system.state.accounts
    uid = accounts.login({'openid': 'alice'}, 'test')['user']['id']
    accounts.reserve(uid, 'existing', 'quiz', {'topic': 'x'})
    job, _ = system.state.features.create_job(uid, 'web-job', {'url': 'https://example.com'})
    await process_material(system.state, uid, job['id'], body=LinkBody(url='https://example.com'), kind='web')
    assert not calls
    assert system.state.features.job(uid, job['id'])['error_code'] == 'AI_BUSY'


@pytest.mark.anyio
async def test_cancel_during_page_read_releases_lease_and_does_not_summarize(system):
    from app.materials.api import process_material, LinkBody
    accounts = system.state.accounts
    uid = accounts.login({'openid': 'alice'}, 'test')['user']['id']
    job, _ = system.state.features.create_job(uid, 'cancel-job', {'url': 'https://example.com'})
    gateway = system.state.gateway = FeatureGateway()
    async def extract(url, **kwargs):
        system.state.features.job(uid, job['id'], cancel=True)
        return {'title': 'page', 'source_type': 'web', 'segments': [{'id': 's1', 'text': 'text'}]}
    system.state.sources.web = extract
    await process_material(system.state, uid, job['id'], body=LinkBody(url='https://example.com'), kind='web')
    assert gateway.calls == []
    assert system.state.features.job(uid, job['id'])['status'] == 'cancelled'
    with accounts.database.session() as s:
        quota = s.scalar(select(Quota).where(Quota.identity == accounts.fingerprint(accounts.settings.wechat_app_id + ':alice')))
        assert quota.busy_id is None
