import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, func

from app.accounts.database import TopicPreparation, Operation, Quota
from app.errors import AppError
from app.quiz_grounding.models import ScopeContent
from app.quiz_grounding.preparation import UnreadablePageScope
from tests.test_mysql_accounts import system, login
from tests.test_grounding_preparation import setup, ScopeGateway


@pytest.mark.anyio
async def test_create_get_retry_conflict_and_foreign_preparation(system):
    state, _ = setup(system)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        assert (await c.post('/api/v1/quiz/preparations', json={'text': 'HTTP'})).status_code == 401
        await login(c)
        response = await c.post('/api/v1/quiz/preparations', headers={'Idempotency-Key': 'same'}, json={'text': 'HTTP'})
        assert response.status_code == 200, response.text
        pid = response.json()['data']['id']
        ready = (await c.get('/api/v1/quiz/preparations/' + pid)).json()['data']
        assert ready['status'] == 'ready'
        again = await c.post('/api/v1/quiz/preparations', headers={'Idempotency-Key': 'same'}, json={'text': 'HTTP'})
        assert again.json()['data'] == ready and len(state.gateway.calls) == 1
        assert (await c.post('/api/v1/quiz/preparations', headers={'Idempotency-Key': 'same'}, json={'text': 'SQL'})).status_code == 409
        assert (await c.post('/api/v1/quiz/preparations/' + pid + '/cancel')).json()['data']['status'] == 'ready'
        await login(c, 'bob')
        assert (await c.get('/api/v1/quiz/preparations/' + pid)).status_code == 404
        assert (await c.post('/api/v1/quiz/preparations/' + pid + '/cancel')).status_code == 404


@pytest.mark.anyio
async def test_url_entry_hint_preserves_instruction_without_search_or_quota(system, monkeypatch):
    state, _ = setup(system)
    monkeypatch.setattr('app.quiz_grounding.api.validate_url', lambda u: u)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        for text, instruction in [('https://example.com/doc', None), ('https://example.com/doc 重点学习应用案例', '重点学习应用案例')]:
            response = await c.post('/api/v1/quiz/preparations', json={'text': text})
            result = response.json()['data']
            assert result['kind'] == 'material_entry' and result['url'] == 'https://example.com/doc'
            assert result['learning_instruction'] == instruction
        assert not state.gateway.calls
        with state.accounts.database.session() as s:
            assert s.scalar(select(func.count()).select_from(TopicPreparation)) == 0


def test_expiration_restart_cancel_race_and_cleanup(system):
    state, uid = setup(system)
    repo = state.grounding
    first, _ = repo.create(uid, 'expired', 'HTTP')
    now = state.accounts.clock()
    state.accounts.clock = lambda: now + 241
    assert repo.get(uid, first['id'])['error_code'] == 'OPERATION_EXPIRED'
    second, _ = repo.create(uid, 'cancel', 'HTTP')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.cancel(uid, second['id']), range(2)))
    assert all(r['status'] == 'cancelled' for r in results)
    assert repo.finish(uid, second['id'], error='LATE_ERROR')['status'] == 'cancelled'
    state.accounts.clock = lambda: now + 25 * 3600
    repo.cleanup()
    with pytest.raises(AppError) as error:
        repo.get(uid, first['id'])
    assert error.value.code == 'NOT_FOUND'
    with pytest.raises(AppError) as error:
        repo.create(uid, 'expired', 'HTTP')
    assert error.value.code == 'PREPARATION_EXPIRED'


def test_deleted_account_rejects_late_preparation_write(system):
    state, uid = setup(system)
    prep, _ = state.grounding.create(uid, 'late', 'HTTP')
    state.accounts.delete_account(uid, {'openid': 'prepare-user'})
    assert state.grounding.finish(uid, prep['id'], error='LATE_ERROR') is None
    with state.accounts.database.session() as s:
        assert s.get(TopicPreparation, prep['id']) is None


class FallbackGateway:
    def __init__(self, clear):
        self.clear, self.calls = clear, []

    async def generate(self, schema, prompt, check=None):
        self.calls.append(prompt)
        assert schema is UnreadablePageScope
        if not self.clear:
            return schema(status='needs_topic')
        scope = ScopeContent(candidates=[{'id': 'c', 'topic': 'HTTP 请求与响应', 'domain': '网络协议', 'description': '用户明确给出主题',
            'focuses': [{'id': 'f', 'name': '请求与响应', 'description': '基础概念',
                        'points': [{'id': 'p', 'name': '请求方法', 'evidence_ids': [], 'evidence_status': 'unverified'}]}]}])
        return schema(status='ready', scope=scope)


@pytest.mark.anyio
@pytest.mark.parametrize('instruction,clear', [(None, False), ('重点学其中案例', False), ('学习 HTTP 请求与响应', True)])
async def test_unreadable_web_never_guesses_page_and_clear_topic_can_handoff(system, instruction, clear):
    from app.materials.api import process_material, LinkBody
    state, uid = setup(system)
    gateway = state.gateway = FallbackGateway(clear)
    async def unavailable(url, **kwargs):
        raise AppError('NO_READABLE_CONTENT', '页面不可读', 502)
    state.sources.web = unavailable
    job, _ = state.features.create_job(uid, 'web', {'url': 'https://example.com/secret-title'})
    await process_material(state, uid, job['id'], body=LinkBody(url='https://example.com/secret-title', learning_instruction=instruction), kind='web')
    result = state.features.job(uid, job['id'])
    if clear:
        assert result['stage'] == 'scope_confirmation' and result['preparation_id']
        assert result['material_id'] is None
        prepared = state.grounding.get(uid, result['preparation_id'])
        assert prepared['grounding']['status'] == 'unverified' and not prepared['evidence']
        with state.accounts.database.session() as s:
            quota = s.scalar(select(Quota).where(Quota.identity == state.accounts.fingerprint(state.settings.wechat_app_id + ':prepare-user')))
            assert quota.material_count == 1 and quota.topic_prepare_count == quota.quiz_count == 0
            assert quota.busy_id is None
    else:
        assert result['status'] == 'failed' and result['material_id'] is None
        assert result['preparation_id'] is None
    assert len(gateway.calls) == (1 if instruction else 0)
    assert all('secret-title' not in prompt for prompt in gateway.calls)


def test_openapi_distinguishes_preparation_and_material_hint(system):
    schema = system.openapi()
    assert '/api/v1/quiz/preparations/{pid}/cancel' in schema['paths']
    assert 'Preparation' in schema['components']['schemas'] and 'MaterialEntryHint' in schema['components']['schemas']
