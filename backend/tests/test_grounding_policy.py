import pytest
from langchain_core.messages import AIMessage

from app.quiz_grounding.agent import RetrievalAgent
from tests.test_grounding_agent import ScriptedModel, calls
from tests.test_grounding_tavily import wire, settings


@pytest.mark.anyio
@pytest.mark.parametrize('query,parameters,expected', [
    ('HTTP 状态码含义', {'query': 'HTTP status codes official documentation', 'max_results': 3},
     {'include_raw_content': False, 'search_depth': 'basic', 'max_results': 3}),
    ('复杂工程机制', {'query': 'engineering architecture official design', 'content_mode': 'full', 'max_results': 8, 'search_depth': 'advanced'},
     {'include_raw_content': 'markdown', 'search_depth': 'advanced', 'max_results': 8}),
    ('法国主题', {'query': 'France patrimoine documentation', 'country': 'france', 'max_results': 4},
     {'country': 'france', 'max_results': 4}),
    ('美国佐治亚州雅典城市历史', {'query': 'Athens Georgia United States city history', 'country': 'united states'},
     {'country': 'united states', 'query': 'Athens Georgia United States city history'}),
    ('法国巴黎最新新闻', {'query': 'Paris France actualités', 'topic': 'news', 'time_range': 'week'},
     {'topic': 'news', 'time_range': 'week'}),
])
async def test_policy_examples_reach_actual_sdk_without_parameter_rewriting(wire, query, parameters, expected):
    # These are reviewable strategy examples, not a claim about live-model quality.
    model = ScriptedModel(replies=[calls(('tavily_search', parameters)), AIMessage(content='done')])
    await RetrievalAgent(settings(), model=model).run(query)
    body = wire['calls'][0]['body']
    assert all(body[k] == value for k, value in expected.items())
    if 'country' not in parameters:
        assert 'country' not in body


@pytest.mark.anyio
async def test_bilingual_searches_keep_source_language_and_evidence(wire):
    model = ScriptedModel(replies=[calls(
        ('tavily_search', {'query': '新技术 官方文档', 'max_results': 3}),
        ('tavily_search', {'query': 'new technology official release documentation', 'max_results': 5, 'content_mode': 'full'})),
        AIMessage(content='done')])
    result = await RetrievalAgent(settings(), model=model).run('用中文学习新技术')
    assert [c['body']['query'] for c in wire['calls']] == ['新技术 官方文档', 'new technology official release documentation']
    assert all('country' not in c['body'] for c in wire['calls'])
    assert result.evidence[0].text == 'body'
