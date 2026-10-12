import httpx
import pytest
from pydantic import ValidationError
from app.config import Settings
from app.main import create_app


def test_test_database_must_be_separate():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_testing=True, mysql_database='same', mysql_test_database='same')


def test_normal_server_rejects_testing_configuration(monkeypatch):
    import app.main as module
    monkeypatch.setattr(module, 'Settings', lambda: Settings(_env_file=None, database_testing=True))
    with pytest.raises(RuntimeError, match='Normal server cannot'):
        module.create_app()


@pytest.mark.parametrize('field', ['session_days', 'quiz_daily_limit', 'ai_minute_limit', 'report_attempt_limit', 'login_minute_limit'])
def test_account_limits_are_positive(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


@pytest.mark.anyio
@pytest.mark.parametrize('path,payload', [
    ('/api/v1/quiz/generate', {'text': 'HTTP', 'question_count': 3, 'difficulty': 'easy'}),
    ('/api/v1/report/generate', {'attempt_id': 'unknown'}),
    ('/api/v1/me', None),
    ('/api/v1/learning', None),
])
async def test_business_api_requires_login_before_database_or_ai(path, payload):
    app = create_app(Settings(_env_file=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        r = await (c.get(path) if payload is None else c.post(path, json=payload))
    assert r.status_code == 401
    assert r.json()['code'] == 'AUTH_REQUIRED'


@pytest.mark.anyio
async def test_wechat_code_exchange_never_accepts_client_identity():
    from app.accounts.wechat import WeChatClient
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={'openid': 'trusted', 'session_key': 'private'})
    client = WeChatClient(Settings(_env_file=None, wechat_app_id='app', wechat_app_secret='secret'), httpx.MockTransport(respond))
    assert await client.exchange('one-use-code') == {'openid': 'trusted', 'unionid': None}
    assert calls[0].url.params['js_code'] == 'one-use-code'
    assert calls[0].url.params['appid'] == 'app'


@pytest.mark.anyio
@pytest.mark.parametrize('reply', [{'errcode': 40029, 'errmsg': 'private details'}, {}, {'openid': ''}])
async def test_wechat_invalid_response_is_sanitized(reply):
    from app.accounts.wechat import WeChatClient
    from app.errors import AppError
    client = WeChatClient(Settings(_env_file=None, wechat_app_id='app', wechat_app_secret='secret'), httpx.MockTransport(lambda r: httpx.Response(200, json=reply)))
    with pytest.raises(AppError) as e:
        await client.exchange('bad')
    assert e.value.code == 'WECHAT_LOGIN_FAILED'
    assert 'private' not in e.value.message
