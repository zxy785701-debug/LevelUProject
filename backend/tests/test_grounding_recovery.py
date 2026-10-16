from datetime import timedelta

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from sqlalchemy import select, func

from app.accounts.database import Operation, TopicPreparation, Quota, QuizRow
from app.models import GenerateRequest
from app.quiz_grounding.generation import process_generation
from app.quiz_grounding.preparation import process_preparation
from tests.helpers import FakeGateway, quiz_payload
from tests.test_mysql_accounts import system, login, confirmed_body
from tests.test_grounding_preparation import ScopeGateway
from tests.test_grounding_agent import ScriptedModel, calls
from tests.test_grounding_tavily import wire
from tests.test_multisource_accounts import FeatureGateway, upload


def fake_clock(state):
    now = [state.accounts.clock()]
    state.accounts.clock = lambda: now[0]
    return now


def exhaust_minute(state, uid):
    with state.accounts.database.session() as s:
        user = state.accounts._user(s, uid)
        quota = state.accounts._quota(s, user.identity)
        quota.calls = [state.accounts.clock()] * 3


@pytest.mark.anyio
async def test_ten_per_minute_runs_prepare_and_review_without_artificial_wait(system, wire):
    state = system.state
    fake_clock(state)
    state.settings.ai_minute_limit = 10
    state.settings.tavily_api_key = SecretStr('test-only')
    state.gateway = ScopeGateway()
    state.retrieval_model = ScriptedModel(replies=[calls(('tavily_search', {'query': str(i)})) for i in range(3)])
    uid = state.accounts.login({'openid': 'fast-flow'}, 'test')['user']['id']
    prep, _ = state.grounding.create(uid, 'fast-scope', 'HTTP')
    async def no_quota_wait(_):
        pytest.fail('A normal prepare + draft + independent review must fit within the minute budget')
    await process_preparation(state, uid, prep['id'], sleep=no_quota_wait)
    prepared = state.grounding.get(uid, prep['id'])
    assert prepared['status'] == 'ready'
    candidate = prepared['content']['candidates'][0]
    focus = candidate['focuses'][0]
    body = GenerateRequest(preparation_id=prepared['id'], scope_version=1, candidate_id=candidate['id'],
                           focus_id=focus['id'], scope_point_ids=[focus['points'][0]['id']], question_count=3)
    oid, _, _, context = state.grounding.submit_generation(uid, 'fast-generation', body)
    state.gateway = FakeGateway(quiz_payload())
    await process_generation(state, uid, oid, body, context, sleep=no_quota_wait)
    assert state.accounts.operation(uid, 'fast-generation')['status'] == 'succeeded'
    with state.accounts.database.session() as db:
        op = db.get(Operation, oid)
        assert op.model_calls == 2 and op.charged == 1  # Draft and independent review both remain.
        quota = db.scalar(select(Quota).where(Quota.identity == state.accounts.fingerprint(state.settings.wechat_app_id + ':fast-flow')))
        assert len(quota.calls) == 6 and quota.quiz_count == 1 and quota.busy_id is None


@pytest.mark.anyio
async def test_three_per_minute_wait_keeps_original_retrieval_and_charges_once(system, wire):
    state = system.state
    now = fake_clock(state)
    state.settings.ai_minute_limit = 3
    state.settings.tavily_api_key = SecretStr('test-only')
    state.gateway = ScopeGateway()
    state.retrieval_model = ScriptedModel(replies=[calls(('tavily_search', {'query': str(i)})) for i in range(3)])
    uid = state.accounts.login({'openid': 'wait'}, 'test')['user']['id']
    prep, _ = state.grounding.create(uid, 'scope-wait', 'HTTP')
    waits = []
    async def sleep(seconds):
        current = state.grounding.get(uid, prep['id'])
        waits.append(current['stage'])
        now[0] += seconds
    await process_preparation(state, uid, prep['id'], sleep=sleep)
    prepared = state.grounding.get(uid, prep['id'])
    assert prepared['status'] == 'ready' and waits and set(waits) == {'waiting_rate_limit'}
    assert len(wire['calls']) == 3
    candidate = prepared['content']['candidates'][0]
    focus = candidate['focuses'][0]
    body = GenerateRequest(preparation_id=prepared['id'], scope_version=1, candidate_id=candidate['id'],
                           focus_id=focus['id'], scope_point_ids=[focus['points'][0]['id']], question_count=3)
    oid, _, fresh, context = state.grounding.submit_generation(uid, 'gen-wait', body)
    assert fresh
    state.gateway = FakeGateway(quiz_payload())
    exhaust_minute(state, uid)
    gen_waits = []
    async def generation_sleep(seconds):
        current = state.accounts.operation(uid, 'gen-wait')
        gen_waits.append((current['stage'], current['retry_after_seconds']))
        now[0] += seconds
    await process_generation(state, uid, oid, body, context, sleep=generation_sleep)
    result = state.accounts.operation(uid, 'gen-wait')
    assert result['status'] == 'succeeded', result
    assert gen_waits and all(stage == 'waiting_rate_limit' and retry > 0 for stage, retry in gen_waits)
    assert len(wire['calls']) == 3  # Waiting never redoes retrieval.
    with state.accounts.database.session() as s:
        operation = s.get(Operation, oid)
        assert operation.model_calls == 2 and operation.charged == 1
        quota = s.scalar(select(Quota).where(Quota.identity == state.accounts.fingerprint(state.settings.wechat_app_id + ':wait')))
        assert quota.quiz_count == 1 and quota.topic_prepare_count == 1 and quota.busy_id is None


@pytest.mark.anyio
async def test_cancel_preparation_while_waiting_stops_before_model_request(system, wire):
    state = system.state
    state.settings.ai_minute_limit = 3
    state.settings.tavily_api_key = SecretStr('test-only')
    state.retrieval_model = ScriptedModel(replies=[AIMessage(content='must not run')])
    uid = state.accounts.login({'openid': 'cancel-wait'}, 'test')['user']['id']
    prep, _ = state.grounding.create(uid, 'cancel-wait', 'HTTP')
    exhaust_minute(state, uid)
    async def sleep(_):
        state.grounding.cancel(uid, prep['id'])
    await process_preparation(state, uid, prep['id'], sleep=sleep)
    assert state.grounding.get(uid, prep['id'])['status'] == 'cancelled'
    assert not state.retrieval_model.requests and not wire['calls']


@pytest.mark.anyio
async def test_generation_deadline_insufficient_for_wait_fails_without_fallback(system):
    state = system.state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        body = GenerateRequest.model_validate(await confirmed_body(c))
        uid = info['user']['id']
        oid, _, _, context = state.grounding.submit_generation(uid, 'short-deadline', body)
        state.settings.ai_minute_limit = 3
        exhaust_minute(state, uid)
        with state.accounts.database.session() as s:
            s.get(Operation, oid).deadline_at = state.grounding.now() + timedelta(seconds=20)
        before = len(state.gateway.calls)
        await process_generation(state, uid, oid, body, context)
        result = state.accounts.operation(uid, 'short-deadline')
        assert result['status'] == 'failed' and result['error_code'] == 'AI_RATE_LIMIT'
        assert len(state.gateway.calls) == before and state.accounts.me(uid)['quota']['remaining'] == 10


@pytest.mark.anyio
async def test_account_deleted_during_wait_cannot_be_revived(system):
    state = system.state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        body = GenerateRequest.model_validate(await confirmed_body(c))
        uid = info['user']['id']
        oid, _, _, context = state.grounding.submit_generation(uid, 'delete-wait', body)
        state.settings.ai_minute_limit = 3
        exhaust_minute(state, uid)
        async def sleep(_): state.accounts.delete_account(uid, {'openid': 'alice'})
        await process_generation(state, uid, oid, body, context, sleep=sleep)
        with state.accounts.database.session() as s:
            assert s.get(Operation, oid) is None
            assert s.scalar(select(func.count()).select_from(QuizRow)) == 0


@pytest.mark.anyio
async def test_lost_worker_same_key_restores_failure_and_never_restarts(system):
    state = system.state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        body = GenerateRequest.model_validate(await confirmed_body(c))
        uid = info['user']['id']
        oid, _, _, context = state.grounding.submit_generation(uid, 'lost-worker', body)
        with state.accounts.database.session() as s:
            user = state.accounts._user(s, uid)
            quota = state.accounts._quota(s, user.identity)
            quota.busy_until = 0
        assert state.accounts.operation(uid, 'lost-worker')['error_code'] == 'OPERATION_EXPIRED'
        recovered_id, restored, fresh, _ = state.grounding.submit_generation(uid, 'lost-worker', body)
        assert recovered_id == oid and restored['status'] == 'failed' and not fresh
        await process_generation(state, uid, oid, body, context)
        assert len(state.gateway.calls) == 1  # Scope only.


@pytest.mark.anyio
async def test_sync_material_respects_rate_error_and_ninety_second_deadline(system):
    state = system.state
    state.gateway = FeatureGateway()
    now = fake_clock(state)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        material = await upload(c)
        uid = info['user']['id']
        state.settings.ai_minute_limit = 3
        exhaust_minute(state, uid)
        body = {'material_id': material['id'], 'point_ids': ['s1'], 'question_count': 3}
        response = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'sync-rate'}, json=body)
        assert response.status_code == 429
        with state.accounts.database.session() as s:
            op = s.scalar(select(Operation).where(Operation.key == 'sync-rate'))
            assert (op.deadline_at - op.created_at).total_seconds() == 90 and op.model_calls == 0
        now[0] += 61
        original = state.gateway
        class LateGateway:
            async def generate(self, *args):
                result = await original.generate(*args)
                now[0] += 91
                return result
        state.gateway = LateGateway()
        response = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'sync-expired'}, json=body)
        assert response.status_code == 504 and response.json()['code'] == 'OPERATION_EXPIRED'
        assert state.accounts.operation(uid, 'sync-expired')['status'] == 'failed'
