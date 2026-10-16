import asyncio
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.quiz_grounding.tavily import TavilyTools


@pytest.fixture
def wire(monkeypatch):
    """Intercept only the HTTP transport: actual official tool/SDK serialize the request."""
    state = {'calls': [], 'body': {'results': [{'url': 'https://example.com/', 'content': 'summary', 'raw_content': 'body'}], 'usage': {'credits': 1}}, 'status': 200, 'delay': 0}

    class Response:
        reason = 'test reason with private details'
        async def __aenter__(self):
            await asyncio.sleep(state['delay'])
            return self
        async def __aexit__(self, *args):
            pass
        @property
        def status(self):
            return state['status']
        async def text(self):
            return json.dumps(state['body'])

    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def post(self, url, *, json, headers):
            state['calls'].append({'url': url, 'body': deepcopy(json), 'headers': dict(headers)})
            return Response()

    monkeypatch.setattr('langchain_tavily._utilities.aiohttp.ClientSession', Session)
    monkeypatch.setattr('app.quiz_grounding.tavily.resolved_ips', lambda _: ['8.8.8.8'])
    return state


def settings(**kwargs):
    return Settings(_env_file=None, tavily_api_key='tvly-test-only', **kwargs)


@pytest.mark.anyio
async def test_official_tools_receive_actual_configured_credentials(wire):
    tools = TavilyTools(settings(), resolve=lambda _: ['8.8.8.8'])
    await tools.search({'query': 'credential transport check'})
    await tools.extract({'urls': ['https://example.com/'], 'content_mode': 'full'})
    assert len(wire['calls']) == 2
    assert all(call['headers']['Authorization'] == 'Bearer tvly-test-only' for call in wire['calls'])


@pytest.mark.anyio
async def test_search_real_sdk_request_and_dynamic_constructor_parameters(wire):
    gateway = TavilyTools(settings())
    result = await gateway.search({'query': 'new framework architecture', 'content_mode': 'full',
                                   'max_results': 8, 'country': 'united states', 'search_depth': 'advanced',
                                   'start_date': '2026-01-01', 'end_date': '2026-10-14',
                                   'include_domains': ['example.com'], 'exclude_domains': ['other.com']})
    assert result.status == 'success' and result.credits == 1
    request = wire['calls'][0]
    assert request['url'] == 'https://api.tavily.com/search'
    body = request['body']
    assert body['max_results'] == 8 and body['country'] == 'united states'
    assert body['include_raw_content'] == 'markdown' and body['search_depth'] == 'advanced'
    assert body['start_date'] == '2026-01-01' and body['end_date'] == '2026-10-14'
    assert body['include_domains'] == ['example.com'] and body['exclude_domains'] == ['other.com']
    assert body['include_answer'] is body['include_images'] is body['auto_parameters'] is False
    assert 'content_mode' not in body


@pytest.mark.anyio
async def test_parallel_calls_do_not_share_country_depth_or_response_size(wire):
    gateway = TavilyTools(settings())
    await asyncio.gather(
        gateway.search({'query': '甲', 'country': 'china', 'max_results': 7, 'content_mode': 'full'}),
        gateway.search({'query': '乙', 'topic': 'news', 'time_range': 'week', 'max_results': 2}),
    )
    requests = {r['body']['query']: r['body'] for r in wire['calls']}
    assert requests['甲']['country'] == 'china' and requests['甲']['max_results'] == 7
    assert 'country' not in requests['乙'] and requests['乙']['max_results'] == 2
    assert requests['乙']['include_raw_content'] is False and requests['乙']['time_range'] == 'week'


@pytest.mark.anyio
@pytest.mark.parametrize('invalid', [
    {'city': 'Shanghai'}, {'country': 'shanghai'}, {'country': 'china', 'topic': 'news'},
    {'max_results': 11}, {'include_answer': True}, {'api_base_url': 'http://localhost'},
    {'time_range': 'week', 'start_date': '2026-01-01'}, {'include_domains': ['https://example.com']},
])
async def test_invalid_search_parameters_never_reach_provider(wire, invalid):
    with pytest.raises(ValidationError):
        await TavilyTools(settings()).search({'query': 'topic', **invalid})
    assert wire['calls'] == []


@pytest.mark.anyio
async def test_configured_result_limit_is_enforced(wire):
    with pytest.raises(ValueError):
        await TavilyTools(settings(search_max_results=4)).search({'query': 'topic', 'max_results': 5})
    assert wire['calls'] == []


@pytest.mark.anyio
async def test_missing_key_and_provider_errors_are_safe(wire):
    result = await TavilyTools(Settings(_env_file=None, tavily_api_key='')).search({'query': 'topic'})
    assert result.reason_code == 'TAVILY_NOT_CONFIGURED' and wire['calls'] == []
    wire['status'] = 401
    result = await TavilyTools(settings()).search({'query': 'private query'})
    assert result.reason_code == 'TAVILY_UNAVAILABLE'
    assert 'private' not in repr(result) and 'tvly-' not in repr(result)


@pytest.mark.anyio
async def test_empty_results_and_external_timeout(wire):
    wire['body'] = {'results': []}
    gateway = TavilyTools(settings(tavily_timeout_seconds=.01))
    assert (await gateway.search({'query': 'topic'})).reason_code == 'TAVILY_EMPTY'
    wire['delay'] = .1
    assert (await gateway.search({'query': 'topic'})).reason_code == 'TAVILY_TIMEOUT'


@pytest.mark.anyio
async def test_extract_full_request_has_no_query_or_chunks_and_depth_can_change(wire):
    gateway = TavilyTools(settings())
    for depth in ('basic', 'advanced'):
        result = await gateway.extract({'urls': ['https://example.com/'], 'extract_depth': depth})
        assert result.status == 'success'
        request = wire['calls'][-1]
        assert request['url'] == 'https://api.tavily.com/extract'
        assert request['body']['extract_depth'] == depth
        assert request['body']['format'] == 'markdown'
        assert 'query' not in request['body'] and 'chunks_per_source' not in request['body']
        assert request['body']['include_images'] is False


@pytest.mark.anyio
async def test_extract_focused_request_and_partial_http_200(wire):
    wire['body']['failed_results'] = [{'url': 'https://bad.example/', 'error': 'private provider detail'}]
    result = await TavilyTools(settings()).extract({
        'urls': ['https://example.com/', 'https://bad.example/'], 'content_mode': 'focused',
        'query': 'architecture', 'chunks_per_source': 4, 'extract_depth': 'advanced'})
    assert result.status == 'partial' and len(result.results) == 1
    assert result.failures == [{'url': 'https://bad.example/', 'code': 'PAGE_UNREADABLE'}]
    body = wire['calls'][0]['body']
    assert body['query'] == 'architecture' and body['chunks_per_source'] == 4
    assert 'private' not in repr(result)


@pytest.mark.anyio
@pytest.mark.parametrize('body', [
    {'results': [], 'failed_results': [{'url': 'https://example.com/', 'error': 'blocked'}]},
    {'results': [{'url': 'https://example.com/', 'raw_content': '   '}]},
    {'error': 'private provider detail'}, {'detail': {'error': 'private provider detail'}},
    {'results': None},
])
async def test_extract_unreadable_empty_and_error_objects_are_not_evidence(wire, body):
    wire['body'] = body
    result = await TavilyTools(settings()).extract({'urls': ['https://example.com/']})
    assert result.status == 'failed' and not result.results
    assert result.failures and result.failures[0]['url'] == 'https://example.com/'
    assert 'private' not in repr(result)


@pytest.mark.anyio
async def test_extract_timeout_cancels_call(wire):
    wire['delay'] = .1
    result = await TavilyTools(settings(tavily_timeout_seconds=.01)).extract({'urls': ['https://example.com/']})
    assert result.reason_code == 'TAVILY_TIMEOUT' and result.status == 'failed'
    assert len(wire['calls']) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('args', [
    {'urls': [f'https://example.com/{i}' for i in range(4)]},
    {'urls': ['https://example.com/'], 'query': 'query'},
    {'urls': ['https://example.com/'], 'content_mode': 'focused', 'query': 'query'},
    {'urls': ['https://example.com/'], 'content_mode': 'focused', 'query': 'query', 'chunks_per_source': 6},
    {'urls': ['https://example.com/'], 'format': 'text'},
])
async def test_extract_invalid_modes_and_batch_do_not_call_provider(wire, args):
    with pytest.raises(ValidationError):
        await TavilyTools(settings()).extract(args)
    assert not wire['calls']
