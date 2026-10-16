import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from sqlalchemy import select

from app.accounts.database import Operation, TopicPreparation, Quota
from app.llm import ModelGateway
from app.quiz_grounding.agent import RetrievalAgent
from app.quiz_grounding.models import QuizDraftResult, QuizReview
from tests.helpers import grounding_payload
from tests.test_mysql_accounts import system, login, confirmed_body
from tests.test_grounding_agent import ScriptedModel, calls
from tests.test_grounding_tavily import wire


class RetryingRunner:
    def __init__(self, always_invalid=False):
        self.requests, self.always_invalid = [], always_invalid

    async def ainvoke(self, messages):
        prompt = messages[-1].content
        self.requests.append(prompt)
        if self.always_invalid or len(self.requests) == 1:
            return {'raw': AIMessage(content='', response_metadata={'finish_reason': 'length'}),
                    'parsed': None, 'parsing_error': None}
        schema = QuizReview if '"title": "QuizReview"' in prompt else QuizDraftResult
        return {'raw': AIMessage(content='{}', response_metadata={'finish_reason': 'stop'}),
                'parsed': grounding_payload(schema, prompt), 'parsing_error': None}


async def no_sleep(_):
    pass


@pytest.mark.anyio
async def test_injected_runner_each_retry_is_counted_and_quiz_charged_once(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        runner = RetryingRunner()
        system.state.gateway = ModelGateway(system.state.settings, runner=runner, sleep=no_sleep)
        result = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'retry'}, json=body)
        assert result.status_code == 200, result.text
        operation = (await c.get('/api/v1/operations/retry')).json()['data']
        assert operation['status'] == 'succeeded', operation
        with system.state.accounts.database.session() as s:
            op = s.scalar(select(Operation).where(Operation.key == 'retry'))
            assert op.model_calls == len(runner.requests) == 3
            assert op.charged == 1
            assert (op.deadline_at - op.created_at).total_seconds() == 300
        assert (await c.get('/api/v1/me')).json()['data']['quota']['remaining'] == 9


@pytest.mark.anyio
async def test_draft_retries_cannot_consume_reserved_review_call(system, wire):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        settings = system.state.settings
        settings.generation_model_call_limit = 5
        settings.tavily_api_key = SecretStr('test-only')
        model = system.state.retrieval_model = ScriptedModel(replies=[calls(('tavily_search', {'query': str(i)})) for i in range(3)])
        runner = RetryingRunner(always_invalid=True)
        system.state.gateway = ModelGateway(settings, runner=runner, sleep=no_sleep)
        await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'reserved'}, json=body)
        operation = (await c.get('/api/v1/operations/reserved')).json()['data']
        assert operation['status'] == 'failed' and operation['error_code'] == 'MODEL_BUDGET_EXHAUSTED'
        with system.state.accounts.database.session() as s:
            op = s.scalar(select(Operation).where(Operation.key == 'reserved'))
            assert op.model_calls == len(model.requests) + len(runner.requests) == 4
            assert op.retrieval_log and len(op.retrieval_log['tools']) == len(wire['calls'])
        assert len(runner.requests) == 1  # One call stays reserved for review.


@pytest.mark.anyio
async def test_prepare_limit_covers_agent_and_scope_runner_retries_without_quiz_charge(system, wire):
    from app.quiz_grounding.preparation import process_preparation
    state = system.state
    state.settings.tavily_api_key = SecretStr('test-only')
    state.retrieval_model = ScriptedModel(replies=[calls(('tavily_search', {'query': str(i)})) for i in range(3)])
    runner = RetryingRunner(always_invalid=True)
    state.gateway = ModelGateway(state.settings, runner=runner, sleep=no_sleep)
    uid = state.accounts.login({'openid': 'budget'}, 'test')['user']['id']
    prep, _ = state.grounding.create(uid, 'prepare-budget', 'HTTP')
    await process_preparation(state, uid, prep['id'])
    assert state.grounding.get(uid, prep['id'])['error_code'] == 'MODEL_BUDGET_EXHAUSTED'
    with state.accounts.database.session() as s:
        row = s.get(TopicPreparation, prep['id'])
        op = s.get(Operation, row.operation_id)
        assert op.model_calls == 5 and len(runner.requests) == 2
        quota = s.scalar(select(Quota).where(Quota.identity == state.accounts.fingerprint(state.settings.wechat_app_id + ':budget')))
        assert quota.topic_prepare_count == 1 and quota.quiz_count == 0 and quota.busy_id is None


@pytest.mark.anyio
async def test_tool_attempts_cache_and_actual_page_counts_match_persisted_state(system, wire):
    state = system.state
    state.settings.tavily_api_key = SecretStr('test-only')
    uid = state.accounts.login({'openid': 'tool-budget'}, 'test')['user']['id']
    prep, _ = state.grounding.create(uid, 'tool-budget', 'HTTP')
    model = ScriptedModel(replies=[calls(
        ('tavily_extract', {'urls': ['https://example.com/']}),
        ('tavily_extract', {'urls': ['https://example.com/']}),
        ('tavily_search', {'query': 'topic', 'unknown': True})), AIMessage(content='done')])
    async def before_model():
        assert state.grounding.model_call(uid, prep['id']) == 0
    async def before_tool(name, pages):
        state.grounding.tool_call(uid, prep['id'], name, pages)
    async def before_pages(pages):
        state.grounding.preparation_page_call(uid, prep['id'], pages)
    result = await RetrievalAgent(state.settings, model=model, before_model=before_model,
                                  before_tool=before_tool, before_pages=before_pages).run('HTTP')
    with state.accounts.database.session() as s:
        row = s.get(TopicPreparation, prep['id'])
        op = s.get(Operation, row.operation_id)
        assert op.tool_calls == result.tool_calls == 3
        assert op.page_attempts == result.page_attempts == 1 and len(wire['calls']) == 1
        assert op.model_calls == len(model.requests) == 2


@pytest.mark.anyio
async def test_invalid_public_url_does_not_count_a_provider_page_attempt(system, wire):
    state = system.state
    state.settings.tavily_api_key = SecretStr('test-only')
    from app.quiz_grounding.tavily import TavilyTools
    tools = TavilyTools(state.settings, resolve=lambda _: ['127.0.0.1'])
    model = ScriptedModel(replies=[calls(('tavily_extract', {'urls': ['http://internal.example/']})), AIMessage(content='done')])
    result = await RetrievalAgent(state.settings, model=model, tools=tools).run('page')
    assert result.tool_calls == 1 and result.page_attempts == 0 and not wire['calls']
