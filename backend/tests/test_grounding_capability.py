import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from openai import BadRequestError

from app.config import Settings
from app.errors import AppError
from app.quiz_grounding.capability import probe_tool_calling


class ToolModel:
    def __init__(self, first=None):
        self.first, self.calls = first, 0

    def bind_tools(self, tools, **kwargs):
        assert tools[0]["function"]["name"] == "capability_echo"
        assert kwargs["tool_choice"] == "auto"
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            if isinstance(self.first, Exception):
                raise self.first
            return self.first if self.first is not None else AIMessage(content="", tool_calls=[{"name": "capability_echo", "args": {"value": "check"}, "id": "call1"}])
        assert isinstance(messages[-1], ToolMessage)
        return AIMessage(content=messages[-1].content)


@pytest.mark.anyio
async def test_tool_round_trip_uses_result_and_two_requests():
    model = ToolModel()
    result = await probe_tool_calling(Settings(_env_file=None), model=model)
    assert result["status"] == "passed" and model.calls == result["model_requests"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize("message", [
    AIMessage(content="I know the answer without calling tools"),
    AIMessage(content="", tool_calls=[{"name": "unknown", "args": {"value": "check"}, "id": "x"}]),
    AIMessage(content="", tool_calls=[{"name": "capability_echo", "args": {"value": "wrong"}, "id": "x"}]),
])
async def test_unsupported_or_invalid_tool_call_fails_without_retry(message):
    model = ToolModel(message)
    with pytest.raises(AppError) as error:
        await probe_tool_calling(Settings(_env_file=None), model=model)
    assert error.value.code == "MODEL_TOOL_CALL_UNSUPPORTED" and model.calls == 1


@pytest.mark.anyio
async def test_provider_tool_rejection_is_sanitized():
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"))
    model = ToolModel(BadRequestError("private provider body", response=response, body=None))
    with pytest.raises(AppError) as error:
        await probe_tool_calling(Settings(_env_file=None), model=model)
    assert error.value.code == "MODEL_TOOL_CALL_UNSUPPORTED"
    assert "private" not in error.value.message and model.calls == 1


@pytest.mark.anyio
async def test_missing_model_key_fails_before_request():
    with pytest.raises(AppError) as error:
        await probe_tool_calling(Settings(_env_file=None))
    assert error.value.code == "MODEL_NOT_CONFIGURED"
