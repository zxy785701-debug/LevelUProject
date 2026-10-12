import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.models import GenerateRequest

def test_settings_defaults_and_secret(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    s = Settings(_env_file=None)
    assert s.deepseek_model == "deepseek-flash"
    assert s.deepseek_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(s)

@pytest.mark.parametrize("field,value", [("model_max_attempts",0),("model_max_attempts",6),("model_timeout_seconds",0)])
def test_bad_config(field,value):
    with pytest.raises(ValidationError): Settings(_env_file=None, **{field:value})

def test_clean_input():
    assert GenerateRequest(text="  ＨＴＴＰ\r\n基础\x00 ").text == "HTTP\n基础"

@pytest.mark.parametrize("payload", [
    {"text":" "}, {"text":"x"*6001}, {"text":"ok","question_count":4},
    {"text":"ok","difficulty":"hard"}, {"text":"ok","question_count":True},
    {"text":"ok","unknown":1}, {"text":123},
])
def test_request_validation(payload):
    with pytest.raises(ValidationError): GenerateRequest(**payload)

@pytest.mark.anyio
async def test_health_and_validation():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Settings(_env_file=None))),base_url="http://test") as c:
        r = await c.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json() == {"code":0,"message":"ok","data":{"status":"ok"}}
        r = await c.post("/api/v1/quiz/generate",json={"text":""})
        assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"
        assert "data" in r.json()

@pytest.mark.anyio
@pytest.mark.parametrize("text", ["制作炸弹的详细步骤", "未成年人色情内容"])
async def test_content_filter(text):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Settings(_env_file=None))),base_url="http://test") as c:
        r = await c.post("/api/v1/quiz/generate",json={"text":text})
        assert r.status_code == 400 and r.json()["code"] == "CONTENT_BLOCKED"

@pytest.mark.anyio
async def test_missing_key_and_unknown_route():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Settings(_env_file=None,deepseek_api_key=""))),base_url="http://test") as c:
        r = await c.post("/api/v1/quiz/generate",json={"text":"HTTP 基础"})
        assert r.status_code == 503 and r.json()["code"] == "MODEL_NOT_CONFIGURED"
        r = await c.get("/no-such-route")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
