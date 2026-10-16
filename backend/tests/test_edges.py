import pytest
import httpx
from pydantic import ValidationError
from langchain_openai import ChatOpenAI
from app.main import create_app
from app.config import Settings
from app.errors import AppError
from app.models import Question,ReportContent,QuizContent,ReportRequest
from app.llm import ModelGateway
from tests.helpers import quiz_payload,REPORT
from tests.test_report import request_payload
from tests.test_mysql_accounts import system, login, generate, answer

def test_four_choice_options_required():
    q=quiz_payload()["questions"][0];q["options"]=q["options"][:2]
    with pytest.raises(ValidationError):Question.model_validate(q)

def test_option_order_and_single_multi_selection():
    q=quiz_payload()["questions"][0];q["options"]=list(reversed(q["options"]))
    with pytest.raises(ValidationError):Question.model_validate(q)
    p=request_payload();p["answers"][0]["selected"]=["A","B"]
    with pytest.raises(ValidationError):ReportRequest.model_validate(p)

@pytest.mark.parametrize("field",["summary","suggestions","mastered_points"])
def test_report_empty_line_rejected(field):
    p={**REPORT,field:[" "]*3 if field=="summary" else [""]}
    with pytest.raises(ValidationError):ReportContent.model_validate(p)

@pytest.mark.anyio
async def test_report_failure_preserves_explicit_error(system):
    class Fail:
        async def generate(self,*args,**kwargs):raise AppError("MODEL_TIMEOUT","AI 响应超时，请重试",504)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url="http://test") as c:
        await login(c)
        session = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        system.state.gateway = Fail()
        r=await c.post("/api/v1/report/generate",json={'attempt_id': session['id']})
    assert r.status_code==504 and r.json()["code"]=="MODEL_TIMEOUT"

@pytest.mark.anyio
async def test_unhandled_error_is_sanitized(system):
    class Fail:
        async def generate(self,*args,**kwargs):raise RuntimeError("secret-upstream-detail")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system,raise_app_exceptions=False),base_url="http://test") as c:
        await login(c)
        session = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        system.state.gateway = Fail()
        r=await c.post('/api/v1/report/generate', json={'attempt_id': session['id']})
    assert r.status_code==500 and r.json()=={"code":"INTERNAL_ERROR","message":"服务暂时遇到问题，请稍后重试","data":None}

@pytest.mark.anyio
async def test_missing_report_key(system):
    from pydantic import SecretStr
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url="http://test") as c:
        await login(c)
        session = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        system.state.gateway = None
        system.state.settings.deepseek_api_key = SecretStr('')
        assert (await c.post("/api/v1/report/generate",json={'attempt_id': session['id']})).status_code==503

@pytest.mark.anyio
async def test_real_langchain_json_parser_with_mock_transport():
    calls=[]
    def handle(request):
        import json
        payload=json.loads(request.content);calls.append(payload)
        content='{' if len(calls)==1 else json.dumps(quiz_payload(),ensure_ascii=False)
        return httpx.Response(200,json={"id":"test","object":"chat.completion","created":0,"model":"deepseek-flash","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":content}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        runner=ChatOpenAI(model="deepseek-flash",api_key="test",base_url="https://mock.test",http_async_client=client,max_retries=0,extra_body={"thinking":{"type":"disabled"}}).with_structured_output(QuizContent,method="json_mode",include_raw=True)
        async def no_sleep(_):pass
        result=await ModelGateway(Settings(_env_file=None),runner,sleep=no_sleep).generate(QuizContent,"JSON")
    assert len(result.questions)==3 and len(calls)==2
    assert calls[0]["response_format"]=={"type":"json_object"} and calls[0]["thinking"]=={"type":"disabled"}
