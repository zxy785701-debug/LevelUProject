from copy import deepcopy
from datetime import timedelta

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.accounts.database import TopicPreparation
from tests.test_mysql_accounts import system, login, answer, confirmed_body
from tests.test_grounding_snapshots import sourced_quiz
from tests.test_grounding_agent import ScriptedModel, calls
from tests.test_grounding_tavily import wire


@pytest.mark.anyio
async def test_combined_wrongs_namespace_same_segment_ids_and_keep_original_scope(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        sessions = []
        for marker in ('first', 'second'):
            quiz = sourced_quiz()
            quiz['source']['segments'][0]['text'] = marker + ' origin passage'
            session = system.state.accounts.store_quiz(info['user']['id'], quiz)
            sessions.append(session)
            for q in quiz['questions']:
                await answer(c, session, q['id'], ['B'] if q['id'] == 'q0' else q['answers'])
        combined = (await c.post('/api/v1/attempts/review', json={'keys': [s['id'] + ':q0' for s in sessions]})).json()['data']
        assert combined['quiz']['source']['segments'] == []
        assert combined['quiz']['questions'][0]['origin']['learning_scope']['focus'] == '错误处理'
        first = (await answer(c, combined, 'review-0', ['A'])).json()['data']['session']
        assert [s['text'] for s in first['quiz']['source']['segments']] == ['first origin passage']
        final = (await answer(c, combined, 'review-1', ['A'])).json()['data']['session']
        segments = final['quiz']['source']['segments']
        assert len({s['id'] for s in segments}) == 2
        assert {s['original_id'] for s in segments} == {'source-0'}
        assert len({s['original_quiz_id'] for s in segments}) == 2
        assert [s['text'] for s in segments] == ['first origin passage', 'second origin passage']
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 40
        resumed = (await c.get('/api/v1/attempts/' + combined['id'])).json()['data']
        assert resumed['quiz']['source'] == final['quiz']['source']
        replay = (await c.post('/api/v1/attempts', json={'quiz_id': sessions[0]['quiz']['id']})).json()['data']
        assert replay['quiz']['source']['segments'] == []
        replayed = (await answer(c, replay, 'q0', ['A'])).json()['data']['session']
        assert replayed['quiz']['source']['segments'][0]['text'] == 'first origin passage'
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 40
        await login(c, 'bob')
        assert (await c.get('/api/v1/attempts/' + combined['id'])).status_code == 404


@pytest.mark.anyio
async def test_generated_source_survives_preparation_cleanup_and_resume(system, wire):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        body = await confirmed_body(c)
        system.state.settings.tavily_api_key = SecretStr('test-only')
        system.state.retrieval_model = ScriptedModel(replies=[calls(('tavily_search', {'query': 'HTTP official'})), AIMessage(content='done')])
        response = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'source-cleanup'}, json=body)
        assert response.status_code == 200
        operation = (await c.get('/api/v1/operations/source-cleanup')).json()['data']
        assert operation['status'] == 'succeeded', operation
        session = operation['result']
        visible = (await answer(c, session, 'q0', ['B'])).json()['data']['session']
        expected = visible['quiz']['source']['segments']
        assert expected and expected[0]['text'] == 'body'
        with system.state.accounts.database.session() as s:
            s.get(TopicPreparation, body['preparation_id']).expires_at = system.state.grounding.now() - timedelta(seconds=1)
        system.state.grounding.cleanup()
        resumed = (await c.get('/api/v1/attempts/' + session['id'])).json()['data']
        assert resumed['quiz']['source']['segments'] == expected
        assert resumed['quiz']['learning_scope']['preparation_id'] == body['preparation_id']
        recovered = (await c.get('/api/v1/operations/source-cleanup')).json()['data']['result']
        assert recovered['quiz']['source']['segments'] == expected


@pytest.mark.anyio
async def test_mixed_legacy_review_never_upgrades_unknown_question_to_verified(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        quiz = sourced_quiz()
        legacy = deepcopy(quiz)
        from uuid import uuid4
        legacy['id'] = str(uuid4())
        legacy.pop('grounding'); legacy.pop('source')
        for q in legacy['questions']:
            q.pop('grounding'); q.pop('source_ids')
        sessions = [system.state.accounts.store_quiz(info['user']['id'], q) for q in (quiz, legacy)]
        for session in sessions: await answer(c, session, 'q0', ['B'])
        combined = (await c.post('/api/v1/attempts/review', json={'keys': [s['id'] + ':q0' for s in sessions]})).json()['data']
        assert combined['quiz']['grounding']['status'] == 'unverified'
        assert combined['quiz']['questions'][1].get('grounding') is None
