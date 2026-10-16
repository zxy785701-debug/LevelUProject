import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from sqlalchemy import select, func

from app.accounts.database import Operation, TopicPreparation, Quota, QuizRow, Attempt
from app.errors import AppError
from app.quiz_grounding.preparation import process_preparation
from app.quiz_grounding.repository import GroundingRepository
from tests.test_mysql_accounts import system
from tests.test_grounding_agent import ScriptedModel, calls
from tests.test_grounding_tavily import wire


class ScopeGateway:
    def __init__(self, topic='HTTP', domain='技术', focus='基础知识'):
        self.topic, self.domain, self.focus = topic, domain, focus
        self.calls = []

    async def generate(self, schema, prompt, check=None):
        self.calls.append(prompt)
        data = json.loads(prompt.rsplit('\n', 1)[-1])
        ids = [s['id'] for s in data['evidence']]
        result = schema.model_validate({'candidates': [{
            'id': 'candidate-1', 'topic': self.topic, 'domain': self.domain, 'description': '需要用户确认的领域',
            'focuses': [{'id': 'focus-1', 'name': self.focus, 'description': '对应用户目标的方向',
                        'points': [{'id': 'point-1', 'name': '具体知识点', 'evidence_ids': ids[:1],
                                    'evidence_status': 'available' if ids else 'unverified'}]}],
        }]})
        if check:
            check(result)
        return result


def setup(system, *, topic='HTTP', domain='技术', focus='基础知识', connected=False):
    state = system.state
    state.grounding = GroundingRepository(state.accounts)
    state.gateway = ScopeGateway(topic, domain, focus)
    state.settings.tavily_api_key = SecretStr('test-only' if connected else '')
    uid = state.accounts.login({'openid': 'prepare-user'}, 'test')['user']['id']
    return state, uid


@pytest.mark.anyio
@pytest.mark.parametrize('topic,domain,focus', [
    ('Harness Engineering', 'AI Agent 工程', 'Agent harness 架构与实践'),
    ('花少2', '综艺及网络文化', '热门梗与名场面'),
])
async def test_prepare_retains_candidate_intent_and_always_waits_for_confirmation(system, wire, topic, domain, focus):
    state, uid = setup(system, topic=topic, domain=domain, focus=focus, connected=True)
    state.retrieval_model = ScriptedModel(replies=[
        calls(('tavily_search', {'query': topic})), AIMessage(content='summary cannot become new evidence')])
    prepared, fresh = state.grounding.create(uid, 'prepare-once', topic)
    assert fresh and prepared['status'] == 'running'
    await process_preparation(state, uid, prepared['id'])
    result = state.grounding.get(uid, prepared['id'])
    assert result['status'] == 'ready' and result['stage'] == 'ready'
    candidate = result['content']['candidates'][0]
    assert candidate['topic'] == topic and candidate['domain'] == domain
    assert candidate['focuses'][0]['name'] == focus
    assert result['grounding']['status'] == 'source_backed' and result['evidence']
    with state.accounts.database.session() as s:
        quota = s.scalar(select(Quota).where(Quota.identity == state.accounts.fingerprint(state.settings.wechat_app_id + ':prepare-user')))
        assert quota.topic_prepare_count == 1 and quota.quiz_count == 0 and quota.busy_id is None
        assert s.scalar(select(func.count()).select_from(QuizRow)) == 0
        assert s.scalar(select(func.count()).select_from(Attempt)) == 0
        row = s.get(TopicPreparation, prepared['id'])
        operation = s.get(Operation, row.operation_id)
        assert operation.status == 'succeeded' and operation.model_calls == 3 and operation.tool_calls == 1
    again, fresh = state.grounding.create(uid, 'prepare-once', topic)
    assert not fresh and again == result and len(state.gateway.calls) == 1


@pytest.mark.anyio
async def test_missing_tavily_auto_fallback_still_requires_scope_confirmation(system):
    state, uid = setup(system)
    prep, _ = state.grounding.create(uid, 'fallback', 'HTTP')
    await process_preparation(state, uid, prep['id'])
    result = state.grounding.get(uid, prep['id'])
    assert result['status'] == 'ready' and result['grounding']['status'] == 'unverified'
    assert result['grounding']['reason_code'] == 'TAVILY_NOT_CONFIGURED'
    point = result['content']['candidates'][0]['focuses'][0]['points'][0]
    assert point['evidence_ids'] == [] and point['evidence_status'] == 'unverified'
    assert result['evidence'] == [] and len(state.gateway.calls) == 1


@pytest.mark.anyio
async def test_daily_prepare_quota_is_separate_and_failure_does_not_refund_it(system):
    state, uid = setup(system)
    state.settings.topic_prepare_daily_limit = 1
    prep, _ = state.grounding.create(uid, 'first', 'HTTP')
    state.grounding.finish(uid, prep['id'], error='TAVILY_TIMEOUT')
    with pytest.raises(AppError) as error:
        state.grounding.create(uid, 'second', 'HTTP')
    assert error.value.code == 'TOPIC_PREPARE_DAILY_LIMIT'
    assert state.accounts.me(uid)['quota']['remaining'] == state.settings.quiz_daily_limit


@pytest.mark.anyio
async def test_model_errors_do_not_create_fallback_scope(system, wire):
    state, uid = setup(system, connected=True)
    state.retrieval_model = ScriptedModel(replies=[NotImplementedError('no tool capability')])
    prep, _ = state.grounding.create(uid, 'unsupported', 'HTTP')
    await process_preparation(state, uid, prep['id'])
    result = state.grounding.get(uid, prep['id'])
    assert result['status'] == 'failed' and result['error_code'] == 'MODEL_TOOL_CALL_UNSUPPORTED'
    assert not state.gateway.calls and not wire['calls']


@pytest.mark.anyio
async def test_atomic_ready_write_rejects_invalid_scope_and_leaves_operation_running(system):
    state, uid = setup(system)
    prep, _ = state.grounding.create(uid, 'invalid', 'HTTP')
    with pytest.raises(ValueError):
        state.grounding.finish(uid, prep['id'], {'scope': None, 'grounding': None})
    assert state.grounding.get(uid, prep['id'])['status'] == 'running'
