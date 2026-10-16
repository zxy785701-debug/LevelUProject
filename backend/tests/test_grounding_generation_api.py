from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.accounts.database import Material, Quota, TopicPreparation
from tests.test_mysql_accounts import system, login, confirmed_body, generate
from tests.test_multisource_accounts import FeatureGateway, upload


@pytest.mark.anyio
async def test_confirmed_generation_returns_operation_and_final_session(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        session = await generate(c)
        assert session['quiz']['learning_scope']['domain'] == '网络协议'
        assert session['quiz']['grounding']['status'] == 'unverified'
        assert all(not q['answers'] for q in session['quiz']['questions'])
        body = await confirmed_body(c)
        recovered = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'first'}, json=body)
        assert recovered.json()['data']['status'] == 'succeeded'
        assert len(system.state.gateway.calls) == 3  # Scope, draft, independent review.


@pytest.mark.anyio
async def test_legacy_text_requires_scope_confirmation_without_charge(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        result = await c.post('/api/v1/quiz/generate', json={'text': 'HTTP', 'question_count': 3})
        assert result.status_code == 409 and result.json()['code'] == 'SCOPE_CONFIRMATION_REQUIRED'
        assert (await c.get('/api/v1/me')).json()['data']['quota']['remaining'] == 10
        assert not system.state.gateway.calls


@pytest.mark.anyio
@pytest.mark.parametrize('change,expected', [
    ({'scope_version': 2}, 409), ({'candidate_id': 'forged'}, 422),
    ({'focus_id': 'forged'}, 422), ({'scope_point_ids': ['forged']}, 422),
])
async def test_invalid_confirmation_is_rejected_before_charge(system, change, expected):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        result = await c.post('/api/v1/quiz/generate', json={**body, **change})
        assert result.status_code == expected, result.text
        assert (await c.get('/api/v1/me')).json()['data']['quota']['remaining'] == 10
        assert len(system.state.gateway.calls) == 1


@pytest.mark.anyio
async def test_expired_and_foreign_preparations_are_rejected(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        await login(c, 'bob')
        assert (await c.post('/api/v1/quiz/generate', json=body)).status_code == 404
        await login(c)
        with system.state.accounts.database.session() as s:
            s.get(TopicPreparation, body['preparation_id']).expires_at = system.state.grounding.now() - timedelta(seconds=1)
        assert (await c.post('/api/v1/quiz/generate', json=body)).status_code == 409
        assert (await c.get('/api/v1/me')).json()['data']['quota']['remaining'] == 10


@pytest.mark.anyio
async def test_material_explicit_background_and_legacy_sync_contract(system):
    system.state.gateway = FeatureGateway()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        material = await upload(c)
        base = {'material_id': material['id'], 'point_ids': ['s1'], 'question_count': 3}
        synchronous = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'sync'}, json=base)
        assert synchronous.status_code == 200, synchronous.text
        assert 'quiz' in synchronous.json()['data'] and 'kind' not in synchronous.json()['data']
        background = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'background'}, json={**base, 'execution': 'background'})
        assert background.status_code == 200, background.text
        assert background.json()['data']['kind'] == 'generation_operation'
        operation = (await c.get('/api/v1/operations/background')).json()['data']
        assert operation['status'] == 'succeeded', operation
        assert operation['result']['quiz']['source']['material_id'] == material['id']


@pytest.mark.anyio
async def test_material_learning_instruction_remains_generation_focus(system):
    system.state.gateway = FeatureGateway()
    instruction = '比较请求的独立性与 Cookie 会话状态的关系'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        material = await upload(c)
        with system.state.accounts.database.session() as s:
            row = s.get(Material, material['id'])
            row.content = {**row.content, 'learning_instruction': instruction}
        result = await c.post('/api/v1/quiz/generate', json={
            'material_id': material['id'], 'point_ids': ['s1'], 'question_count': 3,
            'execution': 'background'})
        assert result.status_code == 200, result.text
        operation = (await c.get('/api/v1/operations/' + result.json()['data']['key'])).json()['data']
        assert operation['status'] == 'succeeded', operation
        scope = operation['result']['quiz']['learning_scope']
        assert scope['input_text'] == instruction and scope['focus'] == instruction
        assert scope['topic'] == material['learning_title']


@pytest.mark.anyio
async def test_succeeded_result_restores_after_preparation_cleanup_and_changed_selection_conflicts(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        session = await generate(c)
        body = await confirmed_body(c)
        with system.state.accounts.database.session() as s:
            s.delete(s.get(TopicPreparation, body['preparation_id']))
        result = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'first'}, json=body)
        assert result.status_code == 200 and result.json()['data']['status'] == 'succeeded'
        assert (await c.get('/api/v1/operations/first')).json()['data']['result']['id'] == session['id']
        conflict = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'first'}, json={**body, 'difficulty': 'medium'})
        assert conflict.status_code == 409 and conflict.json()['code'] == 'IDEMPOTENCY_CONFLICT'
