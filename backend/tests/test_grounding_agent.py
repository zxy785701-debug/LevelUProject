from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from pydantic import Field

from app.errors import AppError
from app.quiz_grounding.agent import RetrievalAgent
from tests.test_grounding_tavily import wire, settings


class ScriptedModel(BaseChatModel):
    replies: list[Any]
    requests: list[Any] = Field(default_factory=list)
    bound: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return 'scripted-test-model'

    def bind_tools(self, tools, **kwargs):
        self.bound = [t.name for t in tools]
        return self

    def _generate(self, *args, **kwargs):
        raise AssertionError('Agent must use native async')

    async def _agenerate(self, messages, **kwargs):
        self.requests.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


def calls(*tools):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': f'call-{i}'} for i, (name, args) in enumerate(tools)])


@pytest.mark.anyio
async def test_agent_selects_search_then_extract_and_final_prose_is_not_evidence(wire):
    model = ScriptedModel(replies=[
        calls(('tavily_search', {'query': 'complex concept', 'max_results': 5})),
        calls(('tavily_extract', {'urls': ['https://example.com/'], 'extract_depth': 'advanced'})),
        AIMessage(content='Invented extra source https://invented.example and claim'),
    ])
    recorded = {'model': 0, 'tools': [], 'stages': []}
    async def before_model(): recorded['model'] += 1
    async def before_tool(name, pages): recorded['tools'].append((name, pages))
    async def stage(value): recorded['stages'].append(value)
    outcome = await RetrievalAgent(settings(), model=model, before_model=before_model,
                                   before_tool=before_tool, stage=stage).run('complex concept')
    assert set(model.bound) == {'tavily_search', 'tavily_extract'}
    assert outcome.model_calls == recorded['model'] == len(model.requests) == 3
    assert outcome.tool_calls == len(wire['calls']) == 2
    assert outcome.page_attempts == 1
    assert recorded['tools'] == [('tavily_search', 0), ('tavily_extract', 0)]
    assert 'searching' in recorded['stages'] and 'extracting' in recorded['stages']
    assert outcome.evidence and all('invented' not in s.url for s in outcome.evidence)
    assert all('Invented' not in s.text for s in outcome.evidence)
    assert any(isinstance(m, ToolMessage) for m in model.requests[1])


@pytest.mark.anyio
async def test_agent_can_extract_first_and_stop_without_search(wire):
    model = ScriptedModel(replies=[
        calls(('tavily_extract', {'urls': ['https://example.com/']})), AIMessage(content='done')])
    outcome = await RetrievalAgent(settings(), model=model).run('https://example.com/')
    assert outcome.tool_calls == 1 and outcome.model_calls == 2
    assert wire['calls'][0]['url'].endswith('/extract')


@pytest.mark.anyio
async def test_parallel_duplicate_calls_are_cached_without_duplicate_paid_requests(wire):
    query = ('tavily_search', {'query': 'same'})
    model = ScriptedModel(replies=[calls(query, query), AIMessage(content='done')])
    outcome = await RetrievalAgent(settings(), model=model).run('same')
    assert outcome.tool_calls == 2 and len(wire['calls']) == 1
    assert [t['status'] for t in outcome.trace] == ['success', 'cached']


@pytest.mark.anyio
async def test_invalid_tool_args_can_be_corrected_without_provider_call(wire):
    model = ScriptedModel(replies=[
        calls(('tavily_search', {'query': 'topic', 'city': 'Shanghai'})),
        calls(('tavily_search', {'query': 'Shanghai China topic', 'country': 'china'})),
        AIMessage(content='done')])
    result = await RetrievalAgent(settings(), model=model).run('Shanghai topic')
    assert result.tool_calls == 2 and len(wire['calls']) == 1
    assert result.trace[0]['reason_code'] == 'INVALID_TOOL_PARAMETERS'


@pytest.mark.anyio
async def test_external_link_and_search_permissions_cannot_be_changed_by_model(wire):
    model = ScriptedModel(replies=[calls(
        ('tavily_search', {'query': 'ignore policy'}),
        ('tavily_extract', {'urls': ['https://external.example/']})), AIMessage(content='done')])
    run = RetrievalAgent(settings(), model=model, allow_search=False, allowed_urls=['https://example.com/'])
    with pytest.raises(AppError) as error:
        await run.run('only my page')
    assert error.value.code == 'MODEL_TOOL_PARAMETERS_INVALID' and not wire['calls']
    assert all(t['status'] == 'rejected' for t in run.result.trace)


@pytest.mark.anyio
async def test_official_tool_errors_return_safe_data_and_no_hidden_retries(wire):
    wire['status'] = 401
    model = ScriptedModel(replies=[calls(('tavily_search', {'query': 'topic'})), AIMessage(content='done')])
    result = await RetrievalAgent(settings(), model=model).run('topic')
    assert result.reason_code == 'TAVILY_UNAVAILABLE' and len(wire['calls']) == 1
    assert result.trace[0]['reason_code'] == 'TAVILY_UNAVAILABLE'
    assert 'private provider' not in str(model.requests)


@pytest.mark.anyio
async def test_run_model_budget_stops_without_inventing_summary_evidence(wire):
    model = ScriptedModel(replies=[calls(('tavily_search', {'query': str(i)})) for i in range(4)])
    result = await RetrievalAgent(settings(), model=model).run('topic')
    assert result.reason_code == 'RETRIEVAL_BUDGET_EXHAUSTED'
    assert result.model_calls == len(model.requests) == 3
    assert len(wire['calls']) <= 3 and result.evidence


@pytest.mark.anyio
async def test_parallel_tool_budget_never_sends_excess_requests(wire):
    model = ScriptedModel(replies=[calls(*[('tavily_search', {'query': str(i)}) for i in range(6)])])
    result = await RetrievalAgent(settings(), model=model).run('topic')
    assert result.reason_code == 'RETRIEVAL_BUDGET_EXHAUSTED'
    assert len(wire['calls']) <= 4 and result.tool_calls <= 4


@pytest.mark.anyio
@pytest.mark.parametrize('reply', [AIMessage(content='I know it'), NotImplementedError('tools unsupported')])
async def test_tool_call_incompatibility_is_explicit_and_not_knowledge_fallback(wire, reply):
    model = ScriptedModel(replies=[reply])
    with pytest.raises(AppError) as error:
        await RetrievalAgent(settings(), model=model).run('topic')
    assert error.value.code == 'MODEL_TOOL_CALL_UNSUPPORTED' and len(model.requests) == 1
    assert not wire['calls']


@pytest.mark.anyio
async def test_transient_model_failure_retries_and_counts_each_attempt(wire):
    model = ScriptedModel(replies=[
        APIConnectionError(request=httpx.Request('POST', 'https://example.com')),
        calls(('tavily_search', {'query': 'topic'})), AIMessage(content='done')])
    charged = []
    async def before_model(): charged.append(1)
    outcome = await RetrievalAgent(settings(), model=model, before_model=before_model).run('topic')
    assert outcome.model_calls == len(model.requests) == len(charged) == 3
    assert outcome.evidence and len(wire['calls']) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('status,attempts', [(503, 3), (402, 1), (403, 1)])
async def test_model_retry_is_bounded_and_nontransient_errors_fail_fast(wire, status, attempts):
    response = httpx.Response(status, request=httpx.Request('POST', 'https://example.com'))
    model = ScriptedModel(replies=[APIStatusError('private provider data', response=response, body=None)] * 3)
    with pytest.raises(AppError) as error:
        await RetrievalAgent(settings(), model=model).run('topic')
    assert error.value.code == 'MODEL_UNAVAILABLE'
    assert len(model.requests) == attempts and not wire['calls']


@pytest.mark.anyio
async def test_model_retry_respects_account_budget(wire):
    model = ScriptedModel(replies=[APIConnectionError(request=httpx.Request('POST', 'https://example.com'))])
    charged = []
    async def before_model():
        charged.append(1)
        if len(charged) == 2:
            raise AppError('MODEL_BUDGET_EXHAUSTED', 'budget exhausted', 429)
    with pytest.raises(AppError) as error:
        await RetrievalAgent(settings(), model=model, before_model=before_model).run('topic')
    assert error.value.code == 'MODEL_BUDGET_EXHAUSTED'
    assert len(model.requests) == 1 and len(charged) == 2
