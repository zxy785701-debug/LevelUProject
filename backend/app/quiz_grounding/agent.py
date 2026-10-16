"""A bounded retrieval-only LangChain Agent; its prose is never evidence."""
import asyncio
import json
import logging
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from openai import AuthenticationError, BadRequestError, RateLimitError, APITimeoutError, APIConnectionError, APIStatusError
from pydantic import ValidationError

from ..errors import AppError
from ..llm import ModelGateway, transient_model_error, model_retry_delay
from .evidence import EvidenceRegistry, EvidenceContextBudget, UNTRUSTED_DATA_RULE, model_evidence
from .models import SearchParameters, ExtractParameters
from .snapshots import EvidenceSegment
from .tavily import TavilyTools
from .policy import retrieval_prompt

logger = logging.getLogger(__name__)

class RetrievalStop(Exception):
    pass


@dataclass
class RetrievalOutcome:
    evidence: list[EvidenceSegment] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    page_attempts: int = 0
    reason_code: str | None = None
    usage: dict = field(default_factory=dict)


async def call_hook(hook, *args):
    if hook is not None:
        await hook(*args)


class RetrievalMiddleware(AgentMiddleware):
    def __init__(self, run):
        self.run = run

    async def awrap_model_call(self, request, handler):
        # Retry only the model request, never replay a completed tool call.
        # Every attempt still passes the account and phase budget checks below.
        attempts = min(self.run.settings.model_max_attempts, self.run.settings.retrieval_model_call_limit)
        for attempt in range(attempts):
            try:
                return await self._model_call(request, handler)
            except (APIConnectionError, APIStatusError, TimeoutError) as exc:
                status = getattr(exc, 'status_code', None)
                delay = model_retry_delay(exc, attempt)
                retry = transient_model_error(exc) and delay is not None and attempt + 1 < attempts and self.run.result.model_calls < self.run.settings.retrieval_model_call_limit
                # Do not log provider bodies, request headers, or user input.
                logger.warning('retrieval_model_error type=%s status=%s retry=%s', type(exc).__name__, status, retry)
                if not retry:
                    raise
                await asyncio.sleep(delay)

    async def _model_call(self, request, handler):
        run = self.run
        if run.result.model_calls >= run.settings.retrieval_model_call_limit:
            raise RetrievalStop()
        await call_hook(run.stage, 'planning')
        await call_hook(run.before_model)
        run.result.model_calls += 1
        # Repeated tool messages also consume context when sent to the model again.
        messages = list(request.messages)
        tool_indices = [i for i, m in enumerate(messages) if isinstance(m, ToolMessage)]
        remaining = run.context_budget.maximum - run.context_budget.used
        per_message = max(0, remaining // max(1, len(tool_indices)) // max(1, run.settings.retrieval_model_call_limit - run.result.model_calls + 1))
        for index in tool_indices:
            message = messages[index]
            try:
                payload = json.loads(message.content)
                sources = [EvidenceSegment.model_validate(s) for s in payload.get('evidence', [])]
                local = EvidenceContextBudget(per_message)
                selected = local.select(sources)
                run.context_budget.used += local.used
                payload['evidence'] = [model_evidence(s) for s in selected]
                payload['data_rule'] = UNTRUSTED_DATA_RULE
                messages[index] = message.model_copy(update={'content': json.dumps(payload, ensure_ascii=False, separators=(',', ':'))})
            except (ValueError, TypeError):
                messages[index] = message.model_copy(update={'content': '{"status":"failed","reason_code":"INVALID_TOOL_RESULT"}'})
        async with asyncio.timeout(run.settings.model_timeout_seconds):
            response = await handler(request.override(messages=messages))
        for message in response.result:
            if isinstance(message, AIMessage):
                if message.invalid_tool_calls:
                    raise AppError('MODEL_TOOL_CALL_UNSUPPORTED', '模型返回了无效工具调用', 503)
                for key, value in (message.usage_metadata or {}).items():
                    if key in ('input_tokens', 'output_tokens', 'total_tokens') and type(value) is int and value >= 0:
                        run.result.usage[key] = run.result.usage.get(key, 0) + value
        return response

    async def awrap_tool_call(self, request, handler):
        run = self.run
        # LangChain can emit a parallel batch; serialize reservations and executions.
        async with run.tool_lock:
            if run.result.tool_calls >= run.settings.retrieval_tool_call_limit:
                raise RetrievalStop()
            run.result.tool_calls += 1
            name, args = request.tool_call['name'], request.tool_call['args']
            pages = 0
            try:
                if name == 'tavily_search':
                    parameters = SearchParameters.model_validate(args)
                    if not run.allow_search:
                        raise ValueError('search disabled')
                elif name == 'tavily_extract':
                    parameters = ExtractParameters.model_validate(args)
                    if run.allowed_urls is not None and not set(parameters.urls) <= run.allowed_urls:
                        raise ValueError('external URL disabled')
                    pages = len(parameters.urls)
                else:
                    raise ValueError('unknown tool')
            except (ValidationError, ValueError):
                await call_hook(run.before_tool, name, 0)
                run.result.trace.append({'tool': name, 'status': 'rejected', 'reason_code': 'INVALID_TOOL_PARAMETERS'})
                return ToolMessage(content='{"status":"failed","reason_code":"INVALID_TOOL_PARAMETERS"}', tool_call_id=request.tool_call['id'])
            if run.result.page_attempts + pages > run.settings.retrieval_max_page_attempts:
                raise RetrievalStop()
            key = name + parameters.model_dump_json()
            cached = key in run.cache
            await call_hook(run.before_tool, name, 0)
            await call_hook(run.stage, 'searching' if name == 'tavily_search' else 'extracting')
            if cached:
                payload = {**run.cache[key], 'status': 'cached'}
                run.result.trace.append({'tool': name, 'parameters': parameters.model_dump(mode='json'), 'status': 'cached'})
                return ToolMessage(content=json.dumps(payload, ensure_ascii=False), tool_call_id=request.tool_call['id'])
            result = await handler(request)
            if run.result.trace:
                run.result.trace[-1]['call_id'] = request.tool_call['id']
            return result


class RetrievalAgent:
    def __init__(self, settings, *, model=None, tools=None, before_model=None, before_tool=None,
                 before_pages=None, stage=None, allow_search=True, allowed_urls=None, context_budget=None):
        self.settings = settings
        self.model = model
        self.tools = tools or TavilyTools(settings)
        self.registry = EvidenceRegistry(settings, resolve=self.tools.resolve)
        self.before_model, self.before_tool, self.stage = before_model, before_tool, stage
        self.before_pages = before_pages
        self.allow_search = allow_search
        self.allowed_urls = set(allowed_urls) if allowed_urls is not None else None
        self.context_budget = context_budget or EvidenceContextBudget(settings.evidence_max_chars // 2)
        self.tool_lock = asyncio.Lock()
        self.cache = {}
        self.result = RetrievalOutcome()

    async def _execute(self, name, parameters):
        async def before_request():
            pages = len(parameters.urls)
            if self.result.page_attempts + pages > self.settings.retrieval_max_page_attempts:
                raise RetrievalStop()
            await call_hook(self.before_pages, pages)
            self.result.page_attempts += pages
        raw = await (self.tools.search(parameters) if name == 'tavily_search' else self.tools.extract(parameters, before_request=before_request))
        result = await self.registry.register(raw, parameters)
        payload = result.model_dump(mode='json')
        self.cache[name + parameters.model_dump_json()] = payload
        self.result.trace.append({'tool': name, 'parameters': parameters.model_dump(mode='json'),
                                 'status': result.status, 'reason_code': result.reason_code,
                                 'credits': result.credits, 'elapsed_ms': result.elapsed_ms,
                                 'source_ids': [s.id for s in result.evidence]})
        return payload

    async def run(self, text, *, system_prompt=None):
        if not self.settings.tavily_available:
            self.result.reason_code = 'TAVILY_NOT_CONFIGURED'
            return self.result
        if self.model is None and not self.settings.deepseek_api_key.get_secret_value():
            raise AppError('MODEL_NOT_CONFIGURED', '请配置模型密钥', 503)
        async def search(**kwargs):
            return await self._execute('tavily_search', SearchParameters.model_validate(kwargs))
        async def extract(**kwargs):
            return await self._execute('tavily_extract', ExtractParameters.model_validate(kwargs))
        tools = [
            StructuredTool.from_function(coroutine=search, name='tavily_search', args_schema=SearchParameters,
                description='Search public knowledge. Choose summary/full, result count, depth, dates and country. Country is only a general-search ranking bias; put cities in query.'),
            StructuredTool.from_function(coroutine=extract, name='tavily_extract', args_schema=ExtractParameters,
                description='Read explicitly chosen public URLs. full reads page body with no query/chunks. focused requires query and chunks_per_source. At most 3 URLs.'),
        ]
        prompt = system_prompt or retrieval_prompt()
        if not self.allow_search:
            prompt += '\n本次禁止搜索或读取外部链接，只允许提取指定网址。'
        try:
            agent = create_agent(self.model or ModelGateway(self.settings).chat_model(), tools,
                system_prompt=prompt, middleware=[
                    ModelCallLimitMiddleware(run_limit=self.settings.retrieval_model_call_limit, exit_behavior='error'),
                    ToolCallLimitMiddleware(run_limit=self.settings.retrieval_tool_call_limit, exit_behavior='error'),
                    RetrievalMiddleware(self),
                ])
            await agent.ainvoke({'messages': [HumanMessage(content=text)]}, config={'recursion_limit': 24})
            if not self.result.tool_calls:
                raise AppError('MODEL_TOOL_CALL_UNSUPPORTED', '模型未执行要求的资料工具调用', 503)
            if self.result.trace and all(t['status'] == 'rejected' for t in self.result.trace):
                raise AppError('MODEL_TOOL_PARAMETERS_INVALID', '模型持续返回无效或越权的工具参数', 503)
        except (RetrievalStop, ModelCallLimitExceededError, ToolCallLimitExceededError):
            self.result.reason_code = 'RETRIEVAL_BUDGET_EXHAUSTED'
        except (NotImplementedError, BadRequestError):
            raise AppError('MODEL_TOOL_CALL_UNSUPPORTED', '当前模型不支持所需工具调用', 503) from None
        except AuthenticationError:
            raise AppError('MODEL_AUTH_ERROR', '模型认证失败，请检查后端配置', 503) from None
        except RateLimitError:
            raise AppError('MODEL_RATE_LIMIT', '模型服务繁忙，请稍后重试', 503) from None
        except (APITimeoutError, TimeoutError):
            raise AppError('MODEL_TIMEOUT', '检索规划超时，请稍后重试', 504) from None
        except (APIConnectionError, APIStatusError):
            raise AppError('MODEL_UNAVAILABLE', '暂时无法连接模型服务', 503) from None
        self.result.evidence = list(self.registry.segments.values())
        if not self.result.evidence and self.result.reason_code is None:
            self.result.reason_code = next((t['reason_code'] for t in reversed(self.result.trace) if t.get('reason_code')), 'NO_RETRIEVED_EVIDENCE')
        return self.result
