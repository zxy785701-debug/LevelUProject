"""Public-source adapters. Direct reads pin validated public IPs across redirects."""
import asyncio
import http.client
import socket
import ssl
from urllib.parse import urlsplit, urljoin
from .parsers import validate_url, resolved_ips, segments_checked, caption_segments, fail
from ..errors import AppError
from ..quiz_grounding.tavily import TavilyTools
from ..quiz_grounding.evidence import EvidenceRegistry
from ..quiz_grounding.models import ExtractParameters, SearchParameters


def public_read(url, timeout=30, max_bytes=5*1024*1024):
    for _ in range(6):
        url = validate_url(url)
        p = urlsplit(url)
        ips = resolved_ips(p.hostname)
        # Validate the very address used by the socket, including a DNS change.
        validate_url(url, resolve=lambda _: ips)
        port = p.port or (443 if p.scheme == 'https' else 80)
        connection = http.client.HTTPConnection(p.hostname, port, timeout=timeout)
        sock = socket.create_connection((ips[0], port), timeout=timeout)
        try:
            if p.scheme == 'https': sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            connection.sock = sock
            connection.request('GET', p.path + ('?' + p.query if p.query else '') or '/', headers={'User-Agent': 'LevelUpLearning/1.0', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location: fail('网页跳转地址缺失', 'SOURCE_UNAVAILABLE', 502)
                url = urljoin(url, location)
                continue
            if response.status != 200: fail('来源无法公开访问，请换链接或粘贴正文', 'SOURCE_UNAVAILABLE', 502)
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes: fail('来源内容超过大小上限', 'MATERIAL_TOO_LARGE')
            return url, data, response.getheader('Content-Type', '')
        finally:
            connection.close()
            sock.close()
    fail('来源跳转过多', 'SOURCE_UNAVAILABLE', 502)


class Sources:
    def __init__(self, settings):
        self.settings = settings
        self.tools = TavilyTools(settings)

    async def web(self, url, *, before_request=None):
        if not self.settings.tavily_available:
            fail('网页读取服务尚未配置，请粘贴正文或补充明确学习主题', 'TAVILY_NOT_CONFIGURED', 503)
        parameters = ExtractParameters(urls=[url], content_mode='full')
        response = await self.tools.extract(parameters, before_request=before_request)
        registry = EvidenceRegistry(self.settings, resolve=self.tools.resolve)
        result = await registry.register(response, parameters)
        if not result.evidence:
            fail('网页暂时无法读取，请粘贴正文或补充明确学习主题', result.reason_code or 'NO_READABLE_CONTENT', 502)
        first = result.evidence[0]
        return segments_checked(first.title or urlsplit(first.url).hostname,
            [s.model_dump(mode='json', exclude_none=True) for s in result.evidence],
            self.settings.material_max_chars, source_type='web', url=first.url,
            extraction_status=result.status, extraction_failures=[f.model_dump() for f in result.failures])

    async def search(self, topic):
        if not self.settings.tavily_available:
            fail('联网补充尚未配置 Tavily 检索服务，可关闭后继续', 'SEARCH_NOT_CONFIGURED', 503)
        parameters = SearchParameters(query=topic[:400], max_results=min(3, self.settings.search_max_results))
        response = await self.tools.search(parameters)
        result = await EvidenceRegistry(self.settings, resolve=self.tools.resolve).register(response, parameters, supplement=True)
        if not result.evidence:
            fail('未检索到可读取的补充来源', result.reason_code or 'NO_READABLE_CONTENT', 502)
        return [s.model_dump(mode='json', exclude_none=True) for s in result.evidence]

    async def video(self, url, start=0, end=None):
        url = await asyncio.to_thread(validate_url, url)
        host, path = urlsplit(url).hostname.lower(), urlsplit(url).path
        if not ((host in ('www.bilibili.com', 'bilibili.com') and path.startswith('/video/')) or host in ('www.youtube.com', 'youtube.com', 'youtu.be', 'm.youtube.com')):
            fail('本期支持 B站和 YouTube 的公开视频字幕链接', 'UNSUPPORTED_PLATFORM')
        if start < 0 or (end is not None and end <= start): fail('片段起止时间不正确', 'INVALID_RANGE')
        def extract():
            from yt_dlp import YoutubeDL
            class Quiet:
                def debug(self, message): pass
                def warning(self, message): pass
                def error(self, message): pass
            with YoutubeDL({'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'noplaylist': True, 'quiet': True, 'logger': Quiet(), 'socket_timeout': self.settings.source_timeout_seconds, 'retries': 0, 'extractor_retries': 0, 'ignoreconfig': True, 'usenetrc': False, 'allowed_extractors': ['youtube', 'BiliBili'], 'extract_flat': False}) as ydl:
                return ydl.extract_info(url, download=False)
        try:
            info = await asyncio.wait_for(asyncio.to_thread(extract), timeout=self.settings.source_timeout_seconds*2)
            if not info or info.get('_type') in ('playlist', 'url', 'url_transparent'): fail('请粘贴单个视频链接', 'UNSUPPORTED_PLATFORM')
            if info.get('duration') and (start >= info['duration'] or (end is not None and end > info['duration'])): fail('片段超过视频时长', 'INVALID_RANGE')
            choices = []
            formats = ('json3', 'json', 'vtt', 'srt')
            for field_index, field in enumerate(('subtitles', 'automatic_captions')):
                for language, tracks in (info.get(field) or {}).items():
                    if not language.startswith(('zh', 'en')): continue
                    for track in tracks:
                        if track.get('ext') not in formats or not (track.get('url') or track.get('data')): continue
                        rank = (0 if language.startswith('zh') else 1, field_index, formats.index(track['ext']), language)
                        choices.append((rank, field, language, track))
            if not choices: fail('没有可访问的中英文字幕，请粘贴视频笔记', 'NO_READABLE_CONTENT')
            _, field, language, choice = min(choices, key=lambda v: v[0])
            if choice.get('data'):
                data = choice['data'].encode('utf-8')
                if len(data) > 2*1024*1024: fail('字幕超过大小上限', 'MATERIAL_TOO_LARGE')
            else:
                _, data, _ = await asyncio.to_thread(public_read, choice['url'], self.settings.source_timeout_seconds, 2*1024*1024)
            return segments_checked(info.get('title') or '视频字幕', caption_segments(data.decode('utf-8-sig'), choice['ext'], start, end), self.settings.material_max_chars,
                source_type='video', url=url, duration=info.get('duration'), caption_kind='人工字幕' if field == 'subtitles' else '自动字幕', language=language, start=start, end=end)
        except AppError: raise
        except Exception: fail('视频字幕暂时无法访问，请重试或粘贴笔记', 'SOURCE_UNAVAILABLE', 502)
