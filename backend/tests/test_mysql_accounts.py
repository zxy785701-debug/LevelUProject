from datetime import datetime, timedelta
import io
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, select
from app.config import Settings
from app.main import create_app
from tests.helpers import FakeGateway, quiz_payload, REPORT


class WeChatStub:
    async def exchange(self, code):
        if code == 'bad':
            from app.errors import AppError
            raise AppError('WECHAT_LOGIN_FAILED', '登录失败', 502)
        return {'openid': code, 'unionid': None}


@pytest.fixture
def system():
    from app.accounts.database import Database, Base
    from app.accounts.repository import Accounts
    settings = Settings(database_testing=True, wechat_app_id='test-app', identity_hash_secret='test-secret-only-' * 3, ai_minute_limit=1000, login_minute_limit=10000)
    assert settings.mysql_user, '请在 backend/.env 配置 MYSQL_*，测试必须使用真实 MySQL'
    database = Database(settings)
    database.migrate()
    with database.engine.begin() as connection:
        from sqlalchemy import text
        actual = connection.scalar(text('SELECT DATABASE()'))
        assert settings.database_testing and actual == settings.mysql_test_database
        assert actual != settings.mysql_database and actual.endswith('_test')
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(delete(table))
    accounts = Accounts(settings, database)
    app = create_app(settings, FakeGateway(quiz_payload()), accounts=accounts, wechat=WeChatStub())
    yield app
    database.engine.dispose()


async def login(c, code='alice'):
    response = await c.post('/api/v1/auth/wechat', json={'code': code, 'agreement_version': '2026-10-12'})
    assert response.status_code == 200, response.text
    data = response.json()['data']
    c.headers['Authorization'] = 'Bearer ' + data['token']
    return data


@pytest.mark.anyio
async def test_login_profile_logout_and_relogin(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        first = await login(c)
        assert first['user']['nickname']
        assert 'openid' not in first['user'] and 'session_key' not in first
        r = await c.patch('/api/v1/me', json={'nickname': '学习者甲'})
        assert r.json()['data']['nickname'] == '学习者甲'
        assert (await c.patch('/api/v1/me', json={'nickname': ' '})).status_code == 422
        assert (await c.post('/api/v1/auth/logout')).status_code == 200
        assert (await c.get('/api/v1/me')).status_code == 401
        second = await login(c)
        assert first['user']['id'] == second['user']['id']
        assert second['user']['nickname'] == '学习者甲'


@pytest.mark.anyio
async def test_avatar_validates_bytes_and_persists(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        assert (await c.post('/api/v1/me/avatar', files={'file': ('fake.png', b'not a picture', 'image/png')})).status_code == 422
        image = io.BytesIO()
        Image.new('RGB', (300, 300), 'red').save(image, 'PNG')
        r = await c.post('/api/v1/me/avatar', files={'file': ('a.png', image.getvalue(), 'image/png')})
        assert r.status_code == 200
        downloaded = await c.get('/api/v1/me/avatar')
        assert downloaded.status_code == 200
        assert Image.open(io.BytesIO(downloaded.content)).size == (256, 256)


async def generate(c, key='first'):
    r = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': key}, json={'text': 'HTTP', 'question_count': 3, 'difficulty': 'easy'})
    assert r.status_code == 200, r.text
    return r.json()['data']


async def answer(c, session, qid, selected):
    return await c.post(f"/api/v1/attempts/{session['id']}/answers", json={'question_id': qid, 'selected': selected, 'elapsed_ms': 1000})


@pytest.mark.anyio
async def test_cloud_answers_rewards_resume_and_no_answer_leak(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        session = await generate(c)
        assert all(not q['answers'] and not q['explanation'] for q in session['quiz']['questions'])
        r = await answer(c, session, 'q0', ['A'])
        assert r.status_code == 200
        assert r.json()['data']['session']['quiz']['questions'][0]['answers'] == ['A']
        assert (await answer(c, session, 'q0', ['A'])).status_code == 200
        assert (await answer(c, session, 'q0', ['B'])).status_code == 409
        me = (await c.get('/api/v1/me')).json()['data']
        assert me['stats']['xp'] == 10 and me['stats']['coins'] == 2
        assert me['stats']['topics'] == 0
        snapshot = (await c.get('/api/v1/learning')).json()['data']
        assert snapshot['sessions'][0]['answers'][0]['selected'] == ['A']
        await answer(c, session, 'q1', ['A', 'B'])
        await answer(c, session, 'q2', ['B'])
        me = (await c.get('/api/v1/me')).json()['data']
        assert me['stats']['xp'] == 20 and me['stats']['topics'] == 1
        assert me['stats']['accuracy'] == 67
        assert len((await c.get('/api/v1/learning')).json()['data']['wrongs']) == 1
        replay = (await c.post('/api/v1/attempts', json={'quiz_id': session['quiz']['id']})).json()['data']
        for q in quiz_payload()['questions']:
            assert (await answer(c, replay, q['id'], q['answers'])).status_code == 200
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 20


@pytest.mark.anyio
async def test_idempotency_ownership_and_report_cache(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        first = await generate(c)
        assert (await generate(c))['id'] == first['id']
        assert len(system.state.gateway.calls) == 1
        mismatch = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'first'}, json={'text': 'other', 'question_count': 3})
        assert mismatch.status_code == 409
        assert (await c.post('/api/v1/report/generate', json={'attempt_id': first['id']})).status_code == 409
        for q in quiz_payload()['questions']:
            await answer(c, first, q['id'], q['answers'])
        system.state.gateway = FakeGateway(REPORT)
        for _ in range(2):
            r = await c.post('/api/v1/report/generate', json={'attempt_id': first['id']})
            assert r.status_code == 200, r.text
            assert r.json()['data']['stats']['xp'] == 30
        assert len(system.state.gateway.calls) == 1
        await login(c, 'bob')
        assert (await c.get(f"/api/v1/attempts/{first['id']}")).status_code == 404
        assert (await answer(c, first, 'q0', ['A'])).status_code == 404
        assert (await c.post('/api/v1/report/generate', json={'attempt_id': first['id']})).status_code == 404
        assert (await c.get('/api/v1/learning')).json()['data']['sessions'] == []


@pytest.mark.anyio
async def test_wrong_review_clear_export_delete_and_quota_survives(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        first = await generate(c)
        for q in quiz_payload()['questions']:
            await answer(c, first, q['id'], ['B'])
        learning = (await c.get('/api/v1/learning')).json()['data']
        keys = list(learning['wrongs'])
        review = (await c.post('/api/v1/attempts/review', json={'keys': keys})).json()['data']
        assert review['mode'] == 'review'
        for q, source in zip(review['quiz']['questions'], quiz_payload()['questions']):
            await answer(c, review, q['id'], source['answers'])
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 0
        assert all(w['mastered'] for w in (await c.get('/api/v1/learning')).json()['data']['wrongs'].values())
        assert 'HTTP' in (await c.get('/api/v1/me/export')).text
        assert (await c.post('/api/v1/wrongs/clear')).status_code == 200
        system.state.settings.quiz_daily_limit = 1
        assert (await c.post('/api/v1/me/delete', json={'code': 'bob', 'confirmation': '注销账号'})).status_code == 403
        assert (await c.post('/api/v1/me/delete', json={'code': 'alice', 'confirmation': '注销账号'})).status_code == 200
        assert (await c.get('/api/v1/me')).status_code == 401
        await login(c)
        r = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'after-delete'}, json={'text': 'HTTP', 'question_count': 3})
        assert r.status_code == 429


@pytest.mark.anyio
async def test_quota_and_report_failure_do_not_erase_records(system):
    from app.errors import AppError
    class Failure:
        async def generate(self, *args):
            raise AppError('MODEL_TIMEOUT', '超时', 504)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        first = await generate(c)
        for q in quiz_payload()['questions']:
            await answer(c, first, q['id'], q['answers'])
        system.state.gateway = Failure()
        for _ in range(3):
            assert (await c.post('/api/v1/report/generate', json={'attempt_id': first['id']})).status_code == 504
        assert (await c.post('/api/v1/report/generate', json={'attempt_id': first['id']})).status_code == 429
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 30
        system.state.settings.quiz_daily_limit = 1
        r = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'second'}, json={'text': 'HTTP', 'question_count': 3})
        assert r.status_code == 429


def test_concurrent_first_answer_is_atomic(system):
    accounts = system.state.accounts
    user = accounts.login({'openid': 'concurrent', 'unionid': None}, '2026-10-12')
    import asyncio
    quiz = asyncio.run(__import__('app.services', fromlist=['generate_quiz']).generate_quiz(__import__('app.models', fromlist=['GenerateRequest']).GenerateRequest(text='HTTP', question_count=3), system.state.settings, system.state.gateway))
    session = accounts.store_quiz(user['user']['id'], quiz)
    def submit(_):
        return accounts.answer(user['user']['id'], session['id'], {'question_id': 'q0', 'selected': ['A'], 'elapsed_ms': 1000})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert all(r['session']['answers'][0]['selected'] == ['A'] for r in results)
    assert accounts.me(user['user']['id'])['stats']['xp'] == 10


@pytest.mark.anyio
async def test_cached_report_works_without_model_configuration(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        a = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, a, q['id'], q['answers'])
        system.state.gateway = FakeGateway(REPORT)
        assert (await c.post('/api/v1/report/generate', json={'attempt_id': a['id']})).status_code == 200
        system.state.gateway = None
        from pydantic import SecretStr
        system.state.settings.deepseek_api_key = SecretStr('')
        assert (await c.post('/api/v1/report/generate', json={'attempt_id': a['id']})).status_code == 200


def test_minute_and_day_boundaries_survive_new_repository(system):
    from app.accounts.repository import Accounts
    accounts = system.state.accounts
    now = [datetime(2026, 10, 12, 15, 59, 58, tzinfo=__import__('datetime').timezone.utc).timestamp()]
    accounts.clock = lambda: now[0]
    user = accounts.login({'openid': 'limits', 'unionid': None}, '2026-10-12')['user']['id']
    system.state.settings.ai_minute_limit = 3
    for i in range(3):
        oid, _ = accounts.reserve(user, str(i), 'quiz', {'i': i})
        accounts.model_call(user, oid)
        accounts.finish(user, oid, {'ok': True})
    from app.errors import AppError
    with pytest.raises(AppError) as e: accounts.reserve(user, 'four', 'quiz', {})
    assert e.value.code == 'AI_RATE_LIMIT'
    now[0] += 60
    other = Accounts(system.state.settings, accounts.database, clock=lambda: now[0])
    oid, _ = other.reserve(user, 'after-minute', 'quiz', {})
    other.model_call(user, oid)
    other.finish(user, oid, {})
    system.state.settings.quiz_daily_limit = 1
    with pytest.raises(AppError): other.reserve(user, 'same-day', 'quiz', {})
    now[0] += 86400
    oid, _ = other.reserve(user, 'next-day', 'quiz', {})
    other.model_call(user, oid)
    other.finish(user, oid, {})


@pytest.mark.anyio
async def test_single_concurrent_ai_request(system):
    import asyncio
    started, release = asyncio.Event(), asyncio.Event()
    original = system.state.gateway
    class Slow:
        async def generate(self, *args):
            started.set()
            await release.wait()
            return await original.generate(*args)
    system.state.gateway = Slow()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        first = asyncio.create_task(generate(c, 'one'))
        await started.wait()
        second = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'two'}, json={'text': 'HTTP', 'question_count': 3})
        assert second.status_code == 409 and second.json()['code'] == 'AI_BUSY'
        release.set()
        await first
        assert len(original.calls) == 1


@pytest.mark.anyio
async def test_invalid_or_expired_token_and_strict_validation(system):
    from app.accounts.database import LoginSession
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        c.headers['Authorization'] = 'Bearer ' + 'x' * 48
        assert (await c.get('/api/v1/me')).status_code == 401
        await login(c)
        for body in ({'text': ''}, {'text': 'HTTP', 'question_count': 4}):
            assert (await c.post('/api/v1/quiz/generate', json=body)).status_code == 422
        assert (await c.post('/api/v1/quiz/generate', json={'text': '制作炸弹的详细步骤'})).status_code == 400
        assert len(system.state.gateway.calls) == 0
        with system.state.accounts.database.session() as s:
            for session in s.scalars(select(LoginSession)): session.expires_at = datetime(2000, 1, 1)
        assert (await c.get('/api/v1/me')).status_code == 401


@pytest.mark.anyio
async def test_transaction_failure_rolls_back_answer_and_reward(system):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.accounts.database import Reward
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system, raise_app_exceptions=False), base_url='http://test') as c:
        await login(c)
        a = await generate(c)
        def fail(session, *_):
            if any(isinstance(v, Reward) for v in session.new): raise RuntimeError('test rollback')
        event.listen(Session, 'before_flush', fail)
        try:
            assert (await answer(c, a, 'q0', ['A'])).status_code == 500
        finally:
            event.remove(Session, 'before_flush', fail)
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 0
        assert (await c.get(f"/api/v1/attempts/{a['id']}")).json()['data']['answers'] == []
        assert (await answer(c, a, 'q0', ['A'])).status_code == 200


@pytest.mark.anyio
async def test_export_contains_real_stats_and_cleanup_expired_markers(system):
    from app.accounts.database import Quota
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        a = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, a, q['id'], q['answers'])
        exported = (await c.get('/api/v1/me/export')).text
        assert ',100,30,6' in exported
        accounts = system.state.accounts
        with accounts.database.session() as s:
            s.add(Quota(identity='retired', day='2000-01-01', retire_after=1))
        accounts.cleanup()
        with accounts.database.session() as s:
            assert s.get(Quota, 'retired') is None


@pytest.mark.anyio
async def test_quiz_and_operation_success_commit_together(system):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.accounts.database import Operation
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system, raise_app_exceptions=False), base_url='http://test') as c:
        await login(c)
        def fail(session, *_):
            if any(isinstance(v, Operation) and v.status == 'succeeded' for v in session.dirty):
                raise RuntimeError('simulate completion write failure')
        event.listen(Session, 'before_flush', fail)
        try:
            response = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'atomic'}, json={'text': 'HTTP', 'question_count': 3})
            assert response.status_code == 500
        finally:
            event.remove(Session, 'before_flush', fail)
        assert (await c.get('/api/v1/learning')).json()['data']['sessions'] == []
        assert (await c.get('/api/v1/operations/atomic')).json()['data']['status'] == 'failed'


def test_expired_operation_same_key_can_be_retried_with_new_key(system):
    from app.errors import AppError
    accounts = system.state.accounts
    now = [accounts.clock()]
    accounts.clock = lambda: now[0]
    uid = accounts.login({'openid': 'expired-operation', 'unionid': None}, '2026-10-12')['user']['id']
    accounts.reserve(uid, 'old', 'quiz', {})
    now[0] += 100000
    with pytest.raises(AppError) as exc:
        accounts.reserve(uid, 'old', 'quiz', {})
    assert exc.value.code == 'OPERATION_EXPIRED'
    oid, _ = accounts.reserve(uid, 'new', 'quiz', {})
    accounts.model_call(uid, oid)
    accounts.finish(uid, oid, {'ok': True})


@pytest.mark.anyio
async def test_expired_generation_does_not_store_late_result(system):
    accounts = system.state.accounts
    now = [accounts.clock()]
    accounts.clock = lambda: now[0]
    original = system.state.gateway
    class Late:
        async def generate(self, *args):
            result = await original.generate(*args)
            now[0] += 100000
            return result
    system.state.gateway = Late()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        response = await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'late'}, json={'text': 'HTTP', 'question_count': 3})
        assert response.status_code == 409
        assert response.json()['code'] == 'OPERATION_EXPIRED'
        assert (await c.get('/api/v1/learning')).json()['data']['sessions'] == []


def test_concurrent_first_login_creates_one_account(system):
    accounts = system.state.accounts
    def sign_in(_):
        return accounts.login({'openid': 'same-wechat', 'unionid': None}, '2026-10-12')
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(sign_in, range(4)))
    assert len({r['user']['id'] for r in responses}) == 1
    assert len({r['token'] for r in responses}) == 4


def test_daily_tenth_eleventh_and_internal_attempt_counts(system):
    from app.errors import AppError
    accounts = system.state.accounts
    now = [datetime(2026, 10, 12, 1).replace(tzinfo=__import__('datetime').timezone.utc).timestamp()]
    accounts.clock = lambda: now[0]
    system.state.settings.ai_minute_limit = 3
    uid = accounts.login({'openid': 'daily-boundary', 'unionid': None}, '2026-10-12')['user']['id']
    for i in range(10):
        oid, _ = accounts.reserve(uid, str(i), 'quiz', {'i': i})
        for _ in range(3): accounts.model_call(uid, oid)
        with pytest.raises(AppError) as exc: accounts.model_call(uid, oid)
        assert exc.value.code == 'AI_RATE_LIMIT'
        accounts.finish(uid, oid, error='MODEL_TIMEOUT')
        now[0] += 61
    assert accounts.me(uid)['quota']['remaining'] == 0
    with pytest.raises(AppError) as exc: accounts.reserve(uid, 'eleven', 'quiz', {})
    assert exc.value.code == 'DAILY_QUOTA_EXCEEDED'


@pytest.mark.anyio
async def test_history_pagination_filters_and_account_scope(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        first = await generate(c, 'history-one')
        for q in quiz_payload()['questions']: await answer(c, first, q['id'], q['answers'])
        await generate(c, 'history-two')
        r = await c.get('/api/v1/attempts?page=1&page_size=1&status=completed&mode=new')
        assert r.status_code == 200
        assert r.json()['data']['total'] == 1
        assert r.json()['data']['items'][0]['id'] == first['id']
        assert (await c.get('/api/v1/attempts?page=2&page_size=1')).json()['data']['total'] == 2
        assert (await c.get('/api/v1/attempts?page_size=0')).status_code == 422
        await login(c, 'history-bob')
        assert (await c.get('/api/v1/attempts')).json()['data']['total'] == 0


@pytest.mark.anyio
async def test_profile_weighted_accuracy_and_shanghai_streak(system):
    from app.accounts.database import Attempt
    accounts = system.state.accounts
    accounts.clock = lambda: datetime(2026, 10, 12, 16, 30).replace(tzinfo=__import__('datetime').timezone.utc).timestamp()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        first = await generate(c, 'stats-one')
        for q in quiz_payload()['questions']: await answer(c, first, q['id'], q['answers'])
        system.state.gateway = FakeGateway(quiz_payload(5))
        r = await c.post('/api/v1/quiz/generate', json={'text': 'HTTP', 'question_count': 5})
        second = r.json()['data']
        for i, q in enumerate(quiz_payload(5)['questions']): await answer(c, second, q['id'], q['answers'] if i < 2 else ['B'])
        with accounts.database.session() as s:
            s.get(Attempt, first['id']).completed_at = datetime(2026, 10, 11, 16, 30)
            s.get(Attempt, second['id']).completed_at = datetime(2026, 10, 12, 16, 10)
        stats = (await c.get('/api/v1/me')).json()['data']['stats']
        assert stats['accuracy'] == 63  # 5 / 8 questions, not the average of two percentages.
        assert stats['topics'] == 2 and stats['streak'] == 2


@pytest.mark.anyio
async def test_progress_wrong_updates_and_avatar_bounds(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        assert (await c.get('/api/v1/me/avatar')).status_code == 404
        assert (await c.post('/api/v1/me/avatar', files={'file': ('large.png', b'x' * (2 * 1024 * 1024 + 1))})).status_code == 422
        session = await generate(c)
        path = f"/api/v1/attempts/{session['id']}/progress"
        assert (await c.put(path, json={'cursor': 3})).status_code == 422
        await answer(c, session, 'q0', ['B'])
        assert (await c.put(path, json={'cursor': 1})).json()['data']['cursor'] == 1
        key = next(iter((await c.get('/api/v1/learning')).json()['data']['wrongs']))
        assert (await c.put('/api/v1/wrongs', json={'key': key, 'mastered': True})).status_code == 200
        assert (await c.get('/api/v1/learning')).json()['data']['wrongs'][key]['mastered']
        assert (await c.put('/api/v1/wrongs', json={'key': 'missing', 'mastered': True})).status_code == 404
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 0
        rows = (await c.get('/api/v1/attempts?status=unfinished&days=7')).json()['data']
        assert rows['total'] == 1


@pytest.mark.anyio
@pytest.mark.parametrize('difficulty,xp,coins', [('easy', 10, 2), ('medium', 15, 3)])
async def test_navigation_any_order_rewards_and_report_snapshot(system, difficulty, xp, coins):
    from app.accounts.database import Reward
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        user = await login(c)
        response = await c.post('/api/v1/quiz/generate', json={'text': 'HTTP', 'question_count': 3, 'difficulty': difficulty})
        session = response.json()['data']
        assert session['quiz']['reward'] == {'xp': xp, 'coins': coins}
        progress = f"/api/v1/attempts/{session['id']}/progress"
        for invalid in [-1, 3, 100, True]:
            assert (await c.put(progress, json={'cursor': invalid})).status_code == 422
        jumped = (await c.put(progress, json={'cursor': 2})).json()['data']
        assert jumped['cursor'] == 2
        assert all(not q['answers'] and not q['explanation'] for q in jumped['quiz']['questions'])
        assert (await answer(c, session, 'missing', ['A'])).status_code == 422
        response = await answer(c, session, 'q2', ['A'])
        assert response.status_code == 200
        assert response.json()['data']['session']['completed_at'] is None
        assert (await c.post('/api/v1/report/generate', json={'attempt_id': session['id']})).status_code == 409
        assert (await answer(c, session, 'q2', ['A'])).status_code == 200
        assert (await answer(c, session, 'q2', ['B'])).status_code == 409
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == xp
        await c.put(progress, json={'cursor': 0})
        assert (await answer(c, session, 'q0', ['A'])).status_code == 200
        assert (await answer(c, session, 'q1', ['A', 'B'])).json()['data']['session']['completed_at']
        me = (await c.get('/api/v1/me')).json()['data']['stats']
        assert (me['xp'], me['coins']) == (3 * xp, 3 * coins)
        with system.state.accounts.database.session() as s:
            rewards = list(s.scalars(select(Reward).where(Reward.user_id == user['user']['id'])))
            assert len(rewards) == 3 and all((r.xp, r.coins) == (xp, coins) for r in rewards)
        system.state.gateway = FakeGateway(REPORT)
        report = (await c.post('/api/v1/report/generate', json={'attempt_id': session['id']})).json()['data']
        assert (report['stats']['xp'], report['stats']['coins']) == (3 * xp, 3 * coins)
        assert f',{3 * xp},{3 * coins}' in (await c.get('/api/v1/me/export')).text
        replay = (await c.post('/api/v1/attempts', json={'quiz_id': session['quiz']['id']})).json()['data']
        for q in reversed(quiz_payload()['questions']):
            assert (await answer(c, replay, q['id'], q['answers'])).status_code == 200
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 3 * xp


@pytest.mark.anyio
async def test_review_out_of_order_updates_matching_wrong_and_never_rewards(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        original = await generate(c)
        for qid in ['q0', 'q1', 'q2']:
            assert (await answer(c, original, qid, ['B'])).status_code == 200
        keys = [f"{original['id']}:q0", f"{original['id']}:q1"]
        review = (await c.post('/api/v1/attempts/review', json={'keys': keys})).json()['data']
        assert (await answer(c, review, 'review-1', ['A', 'B'])).status_code == 200
        wrongs = (await c.get('/api/v1/learning')).json()['data']['wrongs']
        assert wrongs[keys[1]]['mastered'] and not wrongs[keys[0]]['mastered']
        assert (await answer(c, review, 'review-0', ['B'])).json()['data']['session']['completed_at']
        me = (await c.get('/api/v1/me')).json()['data']['stats']
        assert (me['xp'], me['coins']) == (0, 0)


@pytest.mark.anyio
async def test_legacy_medium_quiz_retains_original_reward_rate(system):
    from app.accounts.database import Attempt, QuizRow
    from app.accounts.repository import attempt_stats
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        session = await generate(c)
        with system.state.accounts.database.session() as s:
            attempt = s.get(Attempt, session['id'])
            legacy = {**attempt.quiz, 'difficulty': 'medium'}
            legacy.pop('reward', None)
            attempt.quiz = legacy
            s.get(QuizRow, attempt.quiz_id).content = legacy
        for q in quiz_payload()['questions']:
            assert (await answer(c, session, q['id'], q['answers'])).status_code == 200
        assert (await c.get('/api/v1/me')).json()['data']['stats']['xp'] == 30
        with system.state.accounts.database.session() as s:
            assert attempt_stats(s.get(Attempt, session['id']))['xp'] == 30
        system.state.gateway = FakeGateway(REPORT)
        report = (await c.post('/api/v1/report/generate', json={'attempt_id': session['id']})).json()['data']
        assert report['stats']['xp'] == 30 and report['stats']['coins'] == 6
