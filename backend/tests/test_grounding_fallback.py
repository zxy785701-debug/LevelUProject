from copy import deepcopy
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.accounts.database import TopicPreparation
from tests.test_mysql_accounts import system, login, confirmed_body
from tests.test_grounding_agent import ScriptedModel, calls
from tests.test_grounding_tavily import wire


async def submit(c, body, key='generate'):
    response = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': key}, json=body)
    assert response.status_code == 200, response.text
    return (await c.get('/api/v1/operations/' + key)).json()['data']


@pytest.mark.anyio
@pytest.mark.parametrize('error_status', [200, 429, 500])
async def test_search_failure_automatically_generates_same_scope_unverified(system, wire, error_status):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        state = system.state
        state.settings.tavily_api_key = SecretStr('test-only')
        state.retrieval_model = ScriptedModel(replies=[calls(('tavily_search', {'query': 'HTTP official'})), AIMessage(content='no evidence')])
        wire['status'] = error_status
        wire['body'] = {'results': []}
        operation = await submit(c, body)
        assert operation['status'] == 'succeeded', operation
        quiz = operation['result']['quiz']
        assert quiz['grounding']['status'] == 'unverified' and quiz['grounding']['reason_code'] in ('TAVILY_EMPTY', 'TAVILY_UNAVAILABLE')
        assert quiz['learning_scope']['domain'] == '网络协议'
        assert quiz['source']['segments'] == []
        assert (await c.get('/api/v1/me')).json()['data']['quota']['remaining'] == 9


@pytest.mark.anyio
async def test_fresh_selected_evidence_is_reused_without_more_retrieval(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        with system.state.accounts.database.session() as s:
            row = s.get(TopicPreparation, body['preparation_id'])
            content = deepcopy(row.content)
            content['scope']['candidates'][0]['focuses'][0]['points'][0].update(evidence_ids=['fresh'], evidence_status='available')
            content['evidence'] = [{'id': 'fresh', 'text': 'HTTP requests carry methods.', 'url': 'https://example.com/',
                                    'content_kind': 'snippet', 'retrieved_at': datetime.now(timezone.utc).isoformat()}]
            row.content = content
        system.state.settings.tavily_api_key = SecretStr('test-only')
        system.state.retrieval_model = ScriptedModel(replies=[])
        operation = await submit(c, body)
        assert operation['status'] == 'succeeded' and system.state.retrieval_model.requests == []
        assert operation['result']['quiz']['grounding']['status'] == 'source_backed'


@pytest.mark.anyio
async def test_stale_sources_are_not_misrepresented_after_missing_key_refresh(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        with system.state.accounts.database.session() as s:
            row = s.get(TopicPreparation, body['preparation_id'])
            content = deepcopy(row.content)
            content['scope']['candidates'][0]['focuses'][0]['points'][0].update(evidence_ids=['old'], evidence_status='available')
            content['evidence'] = [{'id': 'old', 'text': 'old snapshot', 'url': 'https://example.com/', 'content_kind': 'snippet',
                                    'retrieved_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}]
            row.content = content
        operation = await submit(c, body)
        assert operation['result']['quiz']['grounding']['status'] == 'unverified'
        assert operation['result']['quiz']['source']['segments'] == []


@pytest.mark.anyio
async def test_model_failure_does_not_take_knowledge_fallback_path(system, wire):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        system.state.settings.tavily_api_key = SecretStr('test-only')
        system.state.retrieval_model = ScriptedModel(replies=[NotImplementedError('no tools')])
        before = len(system.state.gateway.calls)
        operation = await submit(c, body)
        assert operation['status'] == 'failed' and operation['error_code'] == 'MODEL_TOOL_CALL_UNSUPPORTED'
        assert len(system.state.gateway.calls) == before and not wire['calls']


@pytest.mark.anyio
async def test_daily_quota_rejects_generation_without_retrieval_or_fallback(system, wire):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        system.state.settings.quiz_daily_limit = 1
        first = await submit(c, body)
        assert first['status'] == 'succeeded'
        before = len(system.state.gateway.calls)
        blocked = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'new'}, json=body)
        assert blocked.status_code == 429
        assert len(system.state.gateway.calls) == before and not wire['calls']
