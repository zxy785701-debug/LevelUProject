import httpx
import pytest
from sqlalchemy import select
from app.accounts.database import Reward, WrongRow
from tests.test_mysql_accounts import system, login, generate


@pytest.mark.anyio
async def test_delete_owned_record_removes_wrongs_and_cached_results_preserves_rewards(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        user = await login(c)
        first = await generate(c)
        aid = first['id']
        from app.accounts.database import Attempt
        with system.state.accounts.database.session() as db:
            quiz = db.get(Attempt, aid).quiz
        for i, q in enumerate(quiz['questions']):
            selected = q['answers'] if i == 0 else [next(o['id'] for o in q['options'] if o['id'] not in q['answers'])]
            response = await c.post(f'/api/v1/attempts/{aid}/answers', json={'question_id': q['id'], 'selected': selected, 'elapsed_ms': 1000})
            assert response.status_code == 200
        before = (await c.get('/api/v1/me')).json()['data']
        await login(c, 'bob')
        assert (await c.delete(f'/api/v1/attempts/{aid}')).status_code == 404
        await login(c)
        other = await generate(c, 'keep')
        deleted = await c.delete(f'/api/v1/attempts/{aid}')
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()['data']['stats']['xp'] == before['stats']['xp']
        assert deleted.json()['data']['stats']['coins'] == before['stats']['coins']
        assert (await c.get(f'/api/v1/attempts/{aid}')).status_code == 404
        assert (await c.delete(f'/api/v1/attempts/{aid}')).status_code == 404
        learning = (await c.get('/api/v1/learning')).json()['data']
        assert [s['id'] for s in learning['sessions']] == [other['id']]
        assert not learning['wrongs']
        operation = (await c.get('/api/v1/operations/first')).json()['data']
        assert operation['status'] == 'failed' and operation['result'] is None
        assert operation['error_code'] == 'RECORD_DELETED'
        replay = (await c.post('/api/v1/attempts', json={'quiz_id': first['quiz']['id']})).json()['data']
        assert replay['mode'] == 'replay'
        q = quiz['questions'][0]
        result = await c.post(f"/api/v1/attempts/{replay['id']}/answers", json={'question_id': q['id'], 'selected': q['answers'], 'elapsed_ms': 0})
        assert result.json()['data']['user']['stats']['xp'] == before['stats']['xp']
        with system.state.accounts.database.session() as db:
            assert len(list(db.scalars(select(Reward).where(Reward.user_id == user['user']['id'])))) == 1
            assert not list(db.scalars(select(WrongRow)))


@pytest.mark.anyio
async def test_delete_during_report_is_blocked(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        user = await login(c)
        attempt = await generate(c)
        from app.accounts.database import Attempt
        from app.accounts.database import utcnow
        with system.state.accounts.database.session() as db:
            db.get(Attempt, attempt['id']).completed_at = utcnow()
        system.state.accounts.reserve(user['user']['id'], 'report-active', 'report', {'attempt_id': attempt['id']}, attempt['id'])
        result = await c.delete('/api/v1/attempts/' + attempt['id'])
        assert result.status_code == 409 and result.json()['code'] == 'AI_BUSY'
        assert (await c.get('/api/v1/attempts/' + attempt['id'])).status_code == 200
