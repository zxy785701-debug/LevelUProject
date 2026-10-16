from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.accounts.database import QuizRow
from tests.helpers import quiz_payload
from tests.test_mysql_accounts import system, login, answer


def sourced_quiz():
    quiz = quiz_payload()
    quiz.update(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(), source_text='HTTP', difficulty='easy',
        grounding={'status': 'source_backed'},
        learning_scope={'input_text': 'HTTP 错误处理', 'topic': 'HTTP', 'domain': '网络协议', 'focus': '错误处理', 'points': ['请求与会话']})
    segments = []
    for index, kind in enumerate(('snippet', 'full_extract', 'focused_extract')):
        sid = 'source-' + str(index)
        segments.append({'id': sid, 'text': 'real passage ' + str(index), 'title': 'English original ' + str(index),
                         'url': 'https://example.com/' + str(index), 'content_kind': kind,
                         'retrieved_at': '2026-10-14T01:00:00+00:00', 'published_at': None if index == 0 else '2026-10-01',
                         'truncated': index == 2, 'context_truncated': index == 1, 'acquisition_status': 'partial' if index == 2 else 'available'})
        quiz['questions'][index].update(source_ids=[sid], grounding={'status': 'source_backed', 'reason_code': 'private-review-reason'})
    quiz['source'] = {'type': 'topic', 'title': 'HTTP', 'segments': segments}
    return quiz


@pytest.mark.anyio
async def test_sources_and_mappings_are_hidden_until_answered_on_every_session_route(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        uid = info['user']['id']
        oid, _ = system.state.accounts.reserve(uid, 'source-snapshot', 'quiz', {'source': 'test'})
        system.state.accounts.model_call(uid, oid)
        session = system.state.accounts.store_quiz(uid, sourced_quiz(), oid)
        assert session['quiz']['source']['segments'] == []
        assert all(q['source_ids'] == [] and q['grounding'] == {'status': 'source_backed'} for q in session['quiz']['questions'])
        for path in ('/api/v1/attempts/' + session['id'], '/api/v1/operations/source-snapshot'):
            data = (await c.get(path)).json()['data']
            current = data.get('result', data)
            assert current['quiz']['source']['segments'] == []
            assert 'private-review-reason' not in str(current)
        answered = (await answer(c, session, 'q0', ['A'])).json()['data']['session']
        assert answered['quiz']['questions'][0]['source_ids'] == ['source-0']
        assert [s['id'] for s in answered['quiz']['source']['segments']] == ['source-0']
        assert answered['quiz']['questions'][1]['source_ids'] == []
        resumed = (await c.get('/api/v1/operations/source-snapshot')).json()['data']['result']
        assert resumed == answered
        history = (await c.get('/api/v1/attempts')).json()['data']['items'][0]
        assert history['quiz']['source']['segments'] == answered['quiz']['source']['segments']
        with system.state.accounts.database.session() as s:
            full = s.get(QuizRow, session['quiz']['id']).content
            assert len(full['source']['segments']) == 3
            assert full['source']['segments'][1]['context_truncated'] is True
            assert full['source']['segments'][2]['truncated'] is True
            assert full['source']['segments'][0]['published_at'] is None


@pytest.mark.anyio
async def test_source_dates_and_integrity_survive_answer_resume_and_ownership(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        session = system.state.accounts.store_quiz(info['user']['id'], sourced_quiz())
        for q in quiz_payload()['questions']:
            result = await answer(c, session, q['id'], q['answers'])
        ready = result.json()['data']['session']
        sources = ready['quiz']['source']['segments']
        assert sources[0]['retrieved_at'] == '2026-10-14T01:00:00+00:00'
        assert sources[0]['published_at'] is None
        assert [s['content_kind'] for s in sources] == ['snippet', 'full_extract', 'focused_extract']
        await login(c, 'bob')
        assert (await c.get('/api/v1/attempts/' + session['id'])).status_code == 404


def test_legacy_quiz_has_no_invented_verification_status(system):
    uid = system.state.accounts.login({'openid': 'legacy'}, 'test')['user']['id']
    old = quiz_payload()
    old.update(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(), source_text='old', difficulty='easy')
    session = system.state.accounts.store_quiz(uid, old)
    assert session['quiz'].get('grounding') is None and session['quiz'].get('source') is None
    assert all(q.get('grounding') is None for q in session['quiz']['questions'])
