import asyncio
import json
import time

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from openai import APIStatusError
from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.llm import ModelGateway
from app.models import QuizContent
from tests.helpers import quiz_payload
from tests.test_gateway import Runnable, good
from tests.test_grounding_agent import ScriptedModel, calls
from tests.test_grounding_tavily import wire, settings as retrieval_settings
from app.quiz_grounding.agent import RetrievalAgent
from langchain_core.messages import AIMessage


class RecordingRunner(Runnable):
    def __init__(self, items):
        super().__init__(items)
        self.messages = []

    async def ainvoke(self, messages):
        self.messages.append(messages)
        return await super().ainvoke(messages)


def provider_error(status, headers=None):
    return APIStatusError('private provider body', response=httpx.Response(
        status, request=httpx.Request('POST', 'https://example.com'), headers=headers), body=None)


@pytest.mark.anyio
async def test_schema_retry_gets_safe_correction_and_logs_validation_location(caplog):
    payload = quiz_payload()
    payload['questions'][0]['answers'] = []
    payload['private-extra-key'] = 'private model content'
    try:
        QuizContent.model_validate(payload)
    except ValidationError as validation:
        error = OutputParserException('private parser text', llm_output=json.dumps(payload))
        error.__cause__ = validation
    invalid = {**good(), 'parsed': None, 'parsing_error': error}
    runner = RecordingRunner([invalid, good()])
    sleeps, reservations = [], []
    async def sleep(delay): sleeps.append(delay)
    async def before(): reservations.append(1)
    with caplog.at_level('INFO', logger='app.llm'):
        result = await ModelGateway(Settings(_env_file=None), runner, sleep=sleep,
                                    before_call=before, operation_id='test-operation').generate(QuizContent, 'private input')
    assert isinstance(result, QuizContent)
    assert runner.calls == len(reservations) == 2
    correction = '\n'.join(m.content for m in runner.messages[1][:-1])
    assert 'questions.0.answers' in correction
    assert 'SCHEMA_VALIDATION' in caplog.text and 'questions.0.answers' in caplog.text
    assert 'test-operation' in caplog.text and 'retry=True' in caplog.text
    combined = caplog.text + correction
    for secret in ('private input', 'private-extra-key', 'private model content', 'private parser text'):
        assert secret not in combined


@pytest.mark.anyio
@pytest.mark.parametrize('status', [400, 402, 403, 404, 422])
async def test_permanent_provider_status_fails_without_spending_retry_budget(status, caplog):
    runner, sleeps = Runnable([provider_error(status)]), []
    async def sleep(delay): sleeps.append(delay)
    with caplog.at_level('WARNING', logger='app.llm'), pytest.raises(AppError):
        await ModelGateway(Settings(_env_file=None), runner, sleep=sleep).generate(QuizContent, 'JSON')
    assert runner.calls == 1 and not sleeps
    assert f'status={status}' in caplog.text and 'retry=False' in caplog.text
    assert 'private provider body' not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize('header,value', [('retry-after', '3'), ('retry-after-ms', '1500')])
async def test_503_honors_provider_retry_delay_and_reserves_each_request(header, value):
    runner, sleeps, reservations = Runnable([provider_error(503, {header: value}), good()]), [], []
    async def sleep(delay): sleeps.append(delay)
    async def before(): reservations.append(1)
    await ModelGateway(Settings(_env_file=None), runner, sleep=sleep, before_call=before).generate(QuizContent, 'JSON')
    assert sleeps == [float(value) / (1000 if header.endswith('-ms') else 1)]
    assert len(reservations) == runner.calls == 2


@pytest.mark.anyio
async def test_each_attempt_has_a_wall_clock_deadline_even_if_transport_keeps_alive():
    class SlowRunner:
        calls = 0
        cancelled = 0
        async def ainvoke(self, messages):
            self.calls += 1
            try:
                await asyncio.sleep(10)
            finally:
                self.cancelled += 1
    runner = SlowRunner()
    async def sleep(_): pass
    start = time.monotonic()
    with pytest.raises(AppError) as error:
        async with asyncio.timeout(0.5):
            await ModelGateway(Settings(_env_file=None, model_timeout_seconds=0.02, model_max_attempts=2),
                               runner, sleep=sleep).generate(QuizContent, 'JSON')
    assert error.value.code == 'MODEL_TIMEOUT'
    assert runner.calls == runner.cancelled == 2 and time.monotonic() - start < 0.5


@pytest.mark.anyio
async def test_cancellation_and_account_limits_do_not_trigger_extra_requests():
    runner = Runnable([good()])
    async def before(): raise AppError('MODEL_BUDGET_EXHAUSTED', 'budget', 409)
    with pytest.raises(AppError) as error:
        await ModelGateway(Settings(_env_file=None), runner, before_call=before).generate(QuizContent, 'JSON')
    assert error.value.code == 'MODEL_BUDGET_EXHAUSTED' and runner.calls == 0
    runner = Runnable([asyncio.CancelledError()])
    # Runnable only treats Exception as an error; cancellation needs its own runner.
    async def cancel(_): raise asyncio.CancelledError()
    runner.ainvoke = cancel
    with pytest.raises(asyncio.CancelledError):
        await ModelGateway(Settings(_env_file=None), runner).generate(QuizContent, 'JSON')


@pytest.mark.anyio
async def test_retrieval_uses_configured_attempts_and_never_replays_completed_tools(wire, monkeypatch):
    delays, reservations = [], []
    async def sleep(delay): delays.append(delay)
    async def before(): reservations.append(1)
    monkeypatch.setattr('app.quiz_grounding.agent.asyncio.sleep', sleep)
    model = ScriptedModel(replies=[
        provider_error(503, {'retry-after': '2'}), provider_error(503),
        calls(('tavily_search', {'query': 'HTTP'})), AIMessage(content='done')])
    result = await RetrievalAgent(retrieval_settings(), model=model, before_model=before).run('HTTP')
    assert result.evidence
    assert result.model_calls == len(model.requests) == len(reservations) == 3
    assert len(wire['calls']) == 1 and [delay for delay in delays if delay > 0] == [2, 1]


@pytest.mark.anyio
async def test_retrieval_deadline_cancels_a_continuously_open_model_request(wire):
    class SlowModel(ScriptedModel):
        async def _agenerate(self, messages, **kwargs):
            self.requests.append(messages)
            await asyncio.sleep(10)
    model = SlowModel(replies=[])
    config = retrieval_settings()
    config.model_timeout_seconds, config.model_max_attempts = 0.02, 1
    with pytest.raises(AppError) as error:
        async with asyncio.timeout(0.5):
            await RetrievalAgent(config, model=model).run('HTTP')
    assert error.value.code == 'MODEL_TIMEOUT'
    assert len(model.requests) == 1 and not wire['calls']


@pytest.mark.anyio
async def test_model_retry_after_a_search_does_not_replay_that_search(wire, monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.quiz_grounding.agent.asyncio.sleep', sleep)
    model = ScriptedModel(replies=[calls(('tavily_search', {'query': 'HTTP'})),
                                   provider_error(503), AIMessage(content='done')])
    result = await RetrievalAgent(retrieval_settings(), model=model).run('HTTP')
    assert result.evidence and result.model_calls == 3
    assert result.tool_calls == len(wire['calls']) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('value,expected', [('invalid', 0.5), ('NaN', 0.5), ('-1', 0.5), ('61', None)])
async def test_retry_headers_cannot_create_unbounded_waits(value, expected):
    runner, delays = Runnable([provider_error(503, {'retry-after': value}), good()]), []
    async def sleep(delay): delays.append(delay)
    gateway = ModelGateway(Settings(_env_file=None), runner, sleep=sleep)
    if expected is None:
        with pytest.raises(AppError): await gateway.generate(QuizContent, 'JSON')
        assert runner.calls == 1 and not delays
    else:
        await gateway.generate(QuizContent, 'JSON')
        assert runner.calls == 2 and delays == [expected]


@pytest.mark.anyio
async def test_http_date_retry_header_is_honored():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=5), usegmt=True)
    runner, delays = Runnable([provider_error(503, {'retry-after': date}), good()]), []
    async def sleep(delay): delays.append(delay)
    await ModelGateway(Settings(_env_file=None), runner, sleep=sleep).generate(QuizContent, 'JSON')
    assert len(delays) == 1 and 3 <= delays[0] <= 5


@pytest.mark.anyio
async def test_content_filter_stops_without_retrying_the_same_blocked_output():
    payload = good()
    payload['raw'] = AIMessage(content='filtered', response_metadata={'finish_reason': 'content_filter'})
    runner = Runnable([payload])
    with pytest.raises(AppError) as error:
        await ModelGateway(Settings(_env_file=None), runner).generate(QuizContent, 'JSON')
    assert error.value.code == 'MODEL_INVALID_OUTPUT' and runner.calls == 1
