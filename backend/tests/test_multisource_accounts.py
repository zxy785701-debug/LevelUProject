from datetime import datetime, timedelta
import httpx
import pytest
from sqlalchemy import select
from app.accounts.database import Attempt, Quota
from tests.test_mysql_accounts import system, login, generate, answer
from tests.helpers import quiz_payload, grounding_payload


class FeatureGateway:
    def __init__(self): self.calls = []
    async def generate(self, schema, prompt, check=None):
        self.calls.append(prompt)
        grounding = grounding_payload(schema, prompt)
        if grounding is not None:
            data = grounding
        elif schema.__name__ == 'MaterialSummary':
            data = {'title': 'HTTP 学习笔记', 'summary': '学习请求与会话。', 'points': [{'name': '请求与会话', 'segment_ids': ['s1']}]}
        elif schema.__name__ == 'PeriodNarrative':
            data = {'summary': ['继续用例子区分请求与会话。'], 'findings': [], 'suggestions': []}
        else:
            data = quiz_payload(5 if '出 5 道' in prompt else 3)
            for q in data['questions']: q['source_ids'] = ['s1']
        result = schema.model_validate(data)
        if check: check(result)
        return result


async def upload(c, key='upload', text='HTTP 每次请求独立。Cookie 可以保存状态。'):
    response = await c.post('/api/v1/materials/document', headers={'Idempotency-Key': key}, files={'file': ('笔记.txt', text.encode(), 'text/plain')})
    assert response.status_code == 200, response.text
    job = response.json()['data']
    state = (await c.get('/api/v1/material-jobs/' + job['id'])).json()['data']
    assert state['status'] == 'succeeded', state
    return (await c.get('/api/v1/materials/' + state['material_id'])).json()['data']


@pytest.mark.anyio
async def test_document_job_provenance_material_quiz_and_ownership(system):
    gateway = system.state.gateway = FeatureGateway()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        assert (await c.post('/api/v1/materials/document', files={'file': ('a.txt', b'HTTP')})).status_code == 401
        await login(c)
        material = await upload(c)
        again = await upload(c)
        assert material['id'] == again['id'] and len(gateway.calls) == 1
        assert material['segments'][0]['id'] == 's1'
        invalid = await c.post('/api/v1/materials/document', headers={'Idempotency-Key': 'upload'}, files={'file': ('a.txt', b'Changed')})
        assert invalid.status_code == 409
        r = await c.post('/api/v1/quiz/generate', json={'material_id': material['id'], 'question_count': 3, 'difficulty': 'easy', 'point_ids': ['s1']})
        assert r.status_code == 200, r.text
        session = r.json()['data']
        assert session['quiz']['source']['material_id'] == material['id']
        assert session['quiz']['questions'][0]['source_ids'] == []
        assert session['quiz']['source']['segments'] == []
        assert session['quiz']['questions'][0]['answers'] == []
        answered = await answer(c, session, 'q0', ['A'])
        assert answered.json()['data']['session']['quiz']['questions'][0]['source_ids'] == ['s1']
        await login(c, 'bob')
        assert (await c.get('/api/v1/materials/' + material['id'])).status_code == 404
        assert (await c.post('/api/v1/quiz/generate', json={'material_id': material['id']})).status_code == 404
        assert (await c.get('/api/v1/analytics?days=all')).json()['data']['totals']['total'] == 0


@pytest.mark.anyio
async def test_material_errors_limits_no_quiz_charge_and_bad_citations(system):
    from app.errors import AppError
    gateway = system.state.gateway = FeatureGateway()
    system.state.settings.material_daily_limit = 1
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        me = await login(c)
        assert (await c.post('/api/v1/materials/document', files={'file': ('old.doc', b'old')})).status_code == 422
        material = await upload(c)
        assert (await c.get('/api/v1/me')).json()['data']['quota']['remaining'] == 10
        assert (await c.post('/api/v1/materials/document', files={'file': ('a.txt', b'Another')})).status_code == 429
        assert (await c.post('/api/v1/quiz/generate', json={'material_id': material['id'], 'point_ids': ['invented']})).status_code == 422
        supplemented = await c.post('/api/v1/quiz/generate', json={'material_id': material['id'], 'question_count': 3, 'supplement': True})
        assert supplemented.status_code == 200, supplemented.text
        assert supplemented.json()['data']['quiz']['grounding']['reason_code'] == 'SUPPLEMENT_FAILED'
        system.state.gateway = type('Bad', (), {'generate': FeatureGateway.generate, 'calls': []})()
        # Invalid model citations must not become a stored quiz.
        original = system.state.gateway.generate
        async def bad(schema, prompt, check=None):
            result = schema.model_validate(quiz_payload())
            if check: check(result)
            return result
        system.state.gateway.generate = bad
        r = await c.post('/api/v1/quiz/generate', json={'material_id': material['id'], 'question_count': 3})
        assert r.status_code == 502


@pytest.mark.anyio
async def test_map_weighted_analytics_reviews_and_period_cache(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        first = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, first, q['id'], q['answers'] if q['id'] != 'q2' else ['B'])
        replay = (await c.post('/api/v1/attempts', json={'quiz_id': first['quiz']['id']})).json()['data']
        for q in quiz_payload()['questions']: await answer(c, replay, q['id'], q['answers'])
        r = (await c.get('/api/v1/analytics?days=7')).json()['data']
        assert r['totals']['total'] == 3 and r['totals']['accuracy'] == 67
        assert len(r['trend']) == 7 and any(v['accuracy'] is None for v in r['trend'])
        tree = (await c.get('/api/v1/knowledge-map')).json()['data']
        node = tree['topics'][0]['points'][0]
        assert node['total'] == 3 and node['status'] == 'weak'
        await c.post('/api/v1/wrongs/clear')
        assert (await c.get('/api/v1/knowledge-map')).json()['data']['topics'][0]['points'][0]['status'] == 'weak'
        reviewed = (await c.post('/api/v1/attempts/review', json={'keys': [first['id'] + ':q2']})).json()['data']
        await answer(c, reviewed, 'review-0', ['A'])
        assert (await c.get('/api/v1/knowledge-map')).json()['data']['topics'][0]['points'][0]['status'] == 'mastered'
        gateway = system.state.gateway = FeatureGateway()
        report = await c.post('/api/v1/period-reports', json={'days': '7', 'sections': ['overview', 'performance', 'advice']})
        assert report.status_code == 200, report.text
        result = report.json()['data']
        assert result['snapshot']['current']['totals']['accuracy'] == 67
        second = await c.post('/api/v1/period-reports', json={'days': '7', 'sections': ['overview', 'performance', 'advice']})
        assert second.json()['data']['id'] == result['id'] and len(gateway.calls) == 1
        assert (await c.get('/api/v1/period-reports/' + result['id'] + '/export')).json()['data']['text'].find('67%') >= 0
        await login(c, 'bob')
        assert (await c.get('/api/v1/period-reports/' + result['id'])).status_code == 404
        assert (await c.post('/api/v1/period-reports', json={'days': '7', 'sections': ['overview']})).status_code == 409
        assert len(gateway.calls) == 1


@pytest.mark.anyio
async def test_custom_dates_use_completion_shanghai_days_and_invalid_ranges(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c); first = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, first, q['id'], q['answers'])
        with system.state.accounts.database.session() as s:
            a = s.get(Attempt, first['id']); a.completed_at = datetime(2026, 1, 1, 16, 0); a.started_at = datetime(2026, 1, 1, 15, 50)
        r = await c.get('/api/v1/analytics?days=custom&start=2026-01-02&end=2026-01-02')
        assert r.json()['data']['totals']['total'] == 3
        for query in ['days=custom&start=2026-01-03&end=2026-01-02', 'days=custom&start=2020-01-01&end=2026-01-02', 'days=custom&start=2099-01-01&end=2099-01-01']:
            assert (await c.get('/api/v1/analytics?' + query)).status_code == 422
