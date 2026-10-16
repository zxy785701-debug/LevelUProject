"""Per-call official tool instances; no shared mutable SDK configuration or HTTP client."""
import asyncio
import math
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic

from langchain_core.tools import ToolException
from langchain_tavily import TavilySearch, TavilyExtract

from .models import SearchParameters, ExtractParameters
from ..materials.parsers import validate_url, resolved_ips
from ..errors import AppError


@dataclass
class RetrievedResponse:
    tool: str
    results: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    reason_code: str | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    elapsed_ms: int = 0
    credits: float | None = None
    truncated: bool = False

    @property
    def status(self):
        if not self.results:
            return 'failed'
        return 'partial' if self.failures else 'success'


class TavilyTools:
    def __init__(self, settings, *, resolve=None):
        self.settings = settings
        self.resolve = resolve or resolved_ips

    async def _invoke(self, name, tool, arguments, *, timeout_seconds=None, before_request=None):
        started = monotonic()
        response = RetrievedResponse(tool=name)
        if before_request:
            await before_request()
        try:
            async with asyncio.timeout(self.settings.tavily_timeout_seconds if timeout_seconds is None else max(0, timeout_seconds)):
                raw = await tool.ainvoke(arguments)
            if not isinstance(raw, dict) or 'error' in raw or 'detail' in raw:
                response.reason_code = 'TAVILY_UNAVAILABLE'
            elif not isinstance(raw.get('results'), list):
                response.reason_code = 'TAVILY_INVALID_RESPONSE'
            else:
                failures = raw.get('failed_results', [])
                if isinstance(failures, list):
                    response.failures = [{'url': r.get('url'), 'code': 'PAGE_UNREADABLE'}
                                         for r in failures[:20] if isinstance(r, dict)]
                for row in raw['results']:
                    if not isinstance(row, dict):
                        response.failures.append({'code': 'TAVILY_INVALID_RESPONSE'})
                        continue
                    content = row.get('raw_content') if name == 'tavily_extract' else row.get('raw_content') or row.get('content')
                    if isinstance(content, str) and content.strip():
                        response.results.append(row)
                    else:
                        response.failures.append({'url': row.get('url'), 'code': 'PAGE_EMPTY'})
                usage = raw.get('usage')
                credits = usage.get('credits') if isinstance(usage, dict) else None
                if isinstance(credits, (int, float)) and not isinstance(credits, bool) and math.isfinite(credits) and credits >= 0:
                    response.credits = credits
                if not response.results:
                    response.reason_code = 'TAVILY_EMPTY'
        except TimeoutError:
            response.reason_code = 'TAVILY_TIMEOUT'
        except ToolException:
            # SDK raises for empty results; never expose its query/exception text.
            response.reason_code = 'TAVILY_EMPTY'
        except Exception:
            response.reason_code = 'TAVILY_UNAVAILABLE'
        response.elapsed_ms = max(0, int((monotonic() - started) * 1000))
        response.retrieved_at = datetime.now(timezone.utc)
        self._bound_response(response)
        return response

    def _bound_response(self, response):
        """Bound retained SDK data after parsing, not the provider's wire response."""
        limit = self.settings.extract_max_urls_per_call if response.tool == 'tavily_extract' else self.settings.search_max_results
        rows = response.results[:limit]
        response.truncated = len(rows) < len(response.results)
        allowance = self.settings.tool_result_max_bytes // max(1, len(rows))
        retained = []
        for original in rows:
            row = {k: v for k, v in original.items() if k in (
                'url', 'title', 'content', 'raw_content', 'published_date') and isinstance(v, str)}
            # Untrusted metadata must not crowd out the content budget.
            for key, limit in (('url', 2048), ('title', 500), ('published_date', 100)):
                if key in row and len(row[key]) > limit:
                    if key == 'url':
                        row = {}
                        break
                    row[key] = row[key][:limit]
            if not row:
                response.failures.append({'code': 'TAVILY_INVALID_RESPONSE'})
                continue
            content_key = 'raw_content' if row.get('raw_content', '').strip() else 'content'
            content = row.get(content_key, '')
            row['source_chars'] = len(content)
            if content_key == 'raw_content':
                row.pop('content', None)
            # JSON escaping is included in the retained byte limit.
            def size():
                return len(json.dumps(row, ensure_ascii=False).encode('utf-8'))
            if size() > allowance:
                row['truncated'] = True
                response.truncated = True
                low, high = 0, len(content)
                while low < high:
                    mid = (low + high + 1) // 2
                    row[content_key] = content[:mid]
                    if size() <= allowance - 8:
                        low = mid
                    else:
                        high = mid - 1
                row[content_key] = content[:low]
            if not row.get(content_key, '').strip() or size() > allowance:
                response.failures.append({'url': row.get('url'), 'code': 'CONTENT_LIMIT'})
            else:
                retained.append(row)
        response.results = retained
        # Only keep well-formed bounded failure metadata, never provider messages.
        response.failures = [
            {**({'url': f['url']} if isinstance(f.get('url'), str) and len(f['url']) <= 2048 else {}),
             'code': f['code']}
            for f in response.failures[:20]
        ]

    async def search(self, parameters: SearchParameters | dict):
        p = SearchParameters.model_validate(parameters)
        if p.max_results > self.settings.search_max_results:
            raise ValueError('搜索结果条数超过配置上限')
        if not self.settings.tavily_available:
            return RetrievedResponse(tool='tavily_search', reason_code='TAVILY_NOT_CONFIGURED')
        # These fields are constructor-only in langchain-tavily 0.2.18.
        tool = TavilySearch(
            # The SDK stringifies this constructor argument before wrapping it.
            # Passing SecretStr directly would authenticate with its masked text.
            tavily_api_key=self.settings.tavily_api_key.get_secret_value(),
            handle_tool_error=False,
            max_results=p.max_results, country=p.country,
            include_raw_content='markdown' if p.content_mode == 'full' else False,
            include_answer=False, include_images=False, include_image_descriptions=False,
            include_favicon=False, auto_parameters=False, include_usage=True,
        )
        args = p.model_dump(mode='json', exclude_none=True,
                            exclude={'content_mode', 'max_results', 'country'})
        return await self._invoke('tavily_search', tool, args)

    async def extract(self, parameters: ExtractParameters | dict, *, before_request=None):
        started = monotonic()
        p = ExtractParameters.model_validate(parameters)
        if len(p.urls) > self.settings.extract_max_urls_per_call:
            raise ValueError('提取网址数量超过配置上限')
        try:
            async with asyncio.timeout(self.settings.tavily_timeout_seconds):
                urls = [await asyncio.to_thread(validate_url, u, self.resolve) for u in p.urls]
        except TimeoutError:
            return RetrievedResponse(tool='tavily_extract', reason_code='TAVILY_TIMEOUT')
        except AppError:
            return RetrievedResponse(tool='tavily_extract', reason_code='INVALID_URL')
        if not self.settings.tavily_available:
            return RetrievedResponse(tool='tavily_extract', reason_code='TAVILY_NOT_CONFIGURED',
                                     failures=[{'url': u, 'code': 'TAVILY_NOT_CONFIGURED'} for u in p.urls])
        tool = TavilyExtract(
            tavily_api_key=self.settings.tavily_api_key.get_secret_value(), handle_tool_error=False,
            format='markdown', include_images=False, include_favicon=False, include_usage=True,
            chunks_per_source=p.chunks_per_source,
        )
        args = {'urls': urls, 'extract_depth': p.extract_depth}
        if p.content_mode == 'focused':
            args['query'] = p.query
        remaining = self.settings.tavily_timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            return RetrievedResponse(tool='tavily_extract', reason_code='TAVILY_TIMEOUT')
        response = await self._invoke('tavily_extract', tool, args, timeout_seconds=remaining, before_request=before_request)
        response.elapsed_ms = max(0, int((monotonic() - started) * 1000))
        # Missing rows are failures, including the SDK's all-failed ToolException.
        observed = {r.get('url') for r in response.results + response.failures}
        response.failures.extend({'url': u, 'code': response.reason_code or 'PAGE_UNREADABLE'}
                                 for u in urls if u not in observed)
        return response
