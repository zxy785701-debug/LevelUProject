import pytest
from langchain_core.messages import AIMessage
from openai import APITimeoutError, RateLimitError, AuthenticationError, APIConnectionError
import httpx
from app.config import Settings
from app.errors import AppError
from app.llm import ModelGateway
from app.models import QuizContent
from tests.helpers import quiz_payload

class Runnable:
    def __init__(self, items): self.items,self.calls=items,0
    async def ainvoke(self, prompt):
        self.calls+=1
        item=self.items[min(self.calls-1,len(self.items)-1)]
        if isinstance(item,Exception): raise item
        return item

def good(): return {"raw":AIMessage(content="json"),"parsed":QuizContent.model_validate(quiz_payload()),"parsing_error":None}

@pytest.mark.anyio
@pytest.mark.parametrize("bad",[
    {"raw":AIMessage(content=""),"parsed":None,"parsing_error":None},
    {"raw":AIMessage(content="{"),"parsed":None,"parsing_error":ValueError("json")},
    {"raw":AIMessage(content="...",response_metadata={"finish_reason":"length"}),"parsed":None,"parsing_error":None},
])
async def test_invalid_output_retry(bad):
    r=Runnable([bad,good()]); g=ModelGateway(Settings(_env_file=None),r,sleep=lambda _: noop())
    assert isinstance(await g.generate(QuizContent,"JSON"),QuizContent) and r.calls==2

async def noop(): pass

@pytest.mark.anyio
async def test_bounded_retries_and_semantic_validation():
    r=Runnable([good()]); g=ModelGateway(Settings(_env_file=None,model_max_attempts=2),r,sleep=lambda _: noop())
    def reject(_): raise AppError("MODEL_INVALID_OUTPUT","invalid",502)
    with pytest.raises(AppError) as e: await g.generate(QuizContent,"JSON",reject)
    assert r.calls==2 and e.value.code=="MODEL_INVALID_OUTPUT"

@pytest.mark.anyio
@pytest.mark.parametrize("kind,code,attempts",[("timeout","MODEL_TIMEOUT",3),("rate","MODEL_RATE_LIMIT",3),("auth","MODEL_AUTH_ERROR",1),("connection","MODEL_UNAVAILABLE",3)])
async def test_provider_errors(kind,code,attempts):
    req=httpx.Request("POST","https://api.deepseek.com")
    if kind=="timeout": exc=APITimeoutError(request=req)
    elif kind=="connection": exc=APIConnectionError(request=req)
    else:
        status=401 if kind=="auth" else 429
        exc=(AuthenticationError if kind=="auth" else RateLimitError)("sensitive upstream body",response=httpx.Response(status,request=req),body=None)
    r=Runnable([exc]); g=ModelGateway(Settings(_env_file=None),r,sleep=lambda _: noop())
    with pytest.raises(AppError) as e: await g.generate(QuizContent,"JSON")
    assert e.value.code==code and r.calls==attempts and "sensitive" not in e.value.message

def test_adapter_configuration(monkeypatch):
    import app.llm as module
    seen={}
    class Chat:
        def __init__(self,**kwargs): seen.update(kwargs)
        def with_structured_output(self,schema,**kwargs): seen.update(kwargs);return self
    monkeypatch.setattr(module,"ChatOpenAI",Chat)
    ModelGateway(Settings(_env_file=None,deepseek_api_key="local-test")).runnable(QuizContent)
    assert seen["extra_body"]=={"thinking":{"type":"disabled"}}
    assert seen["method"]=="json_mode" and seen["include_raw"] is True and seen["max_retries"]==0
