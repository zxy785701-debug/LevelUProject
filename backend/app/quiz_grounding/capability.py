"""Explicit deployment probe; never invoked automatically on user requests."""
import asyncio
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
    BadRequestError, RateLimitError,
)

from ..config import Settings
from ..errors import AppError
from ..llm import ModelGateway


PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "capability_echo",
        "description": "Run the tool-calling capability check. Returns a verification token.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    },
}


def _unsupported():
    return AppError("MODEL_TOOL_CALL_UNSUPPORTED", "当前模型未通过工具调用验证，请检查模型配置", 503)


async def probe_tool_calling(settings: Settings, *, model=None):
    """Check a real tool-call round trip with two bounded, non-retried requests.

    The tool is local and side-effect free; no Tavily call or account mutation.
    A fake model can be injected to verify rejection and sanitization offline.
    """
    if model is None and not settings.deepseek_api_key.get_secret_value():
        raise AppError("MODEL_NOT_CONFIGURED", "尚未配置模型密钥", 503)
    model = model if model is not None else ModelGateway(settings).chat_model()
    token = "verified-" + uuid4().hex
    messages = [
        SystemMessage(content="Call capability_echo exactly once with value 'check'. After its result, reply with only the returned verification token. Do not invent a token."),
        HumanMessage(content="Run the tool capability check now."),
    ]
    try:
        runner = model.bind_tools([PROBE_TOOL], tool_choice="auto", max_tokens=128, temperature=0)
        async with asyncio.timeout(2 * settings.model_timeout_seconds + 5):
            first = await runner.ainvoke(messages)
            if not isinstance(first, AIMessage) or first.invalid_tool_calls or len(first.tool_calls) != 1:
                raise _unsupported()
            call = first.tool_calls[0]
            if call["name"] != "capability_echo" or call["args"] != {"value": "check"} or not call.get("id"):
                raise _unsupported()
            messages.extend([first, ToolMessage(content=token, tool_call_id=call["id"])])
            second = await runner.ainvoke(messages)
            if not isinstance(second, AIMessage) or second.tool_calls or second.invalid_tool_calls or second.content != token:
                raise _unsupported()
    except AuthenticationError:
        raise AppError("MODEL_AUTH_ERROR", "模型认证失败，请检查后端密钥", 503) from None
    except RateLimitError:
        raise AppError("MODEL_RATE_LIMIT", "AI 服务繁忙，请稍后重试", 503) from None
    except (APITimeoutError, asyncio.TimeoutError):
        raise AppError("MODEL_TIMEOUT", "模型工具调用验证超时", 504) from None
    except (NotImplementedError, BadRequestError):
        raise _unsupported() from None
    except (APIConnectionError, APIStatusError):
        raise AppError("MODEL_UNAVAILABLE", "暂时无法连接 AI 服务", 503) from None
    usage = {}
    for response in (first, second):
        for key, value in (response.usage_metadata or {}).items():
            if key in ("input_tokens", "output_tokens", "total_tokens") and type(value) is int and value >= 0:
                usage[key] = usage.get(key, 0) + value
    return {"status": "passed", "model": settings.deepseek_model, "model_requests": 2, "tool_calls": 1, "usage": usage}
