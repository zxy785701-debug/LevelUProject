import pytest
from app.config import Settings
from app.errors import AppError
from app.materials.sources import Sources, public_read
from tests.test_grounding_tavily import wire, settings


@pytest.mark.anyio
async def test_reader_uses_official_extract_only_for_requested_page(wire):
    wire['body'] = {'results': [{'url': 'https://example.com', 'title': 'Real title',
                                'raw_content': 'Actual extracted text. External link https://other.example/'}]}
    adapter = Sources(settings())
    result = await adapter.web('https://example.com')
    assert len(wire['calls']) == 1
    assert wire['calls'][0]['url'].endswith('/extract')
    assert wire['calls'][0]['body']['urls'] == ['https://example.com']
    assert 'query' not in wire['calls'][0]['body']
    assert result['url'] == 'https://example.com' and result['title'] == 'Real title'
    assert result['segments'][0]['content_kind'] == 'full_extract'
    adapter.settings.material_max_chars = 2
    with pytest.raises(AppError): await adapter.web('https://example.com')


def test_direct_reader_pins_socket_ip_and_rejects_private_redirect(monkeypatch):
    import app.materials.sources as sources
    from app.materials.parsers import validate_url
    monkeypatch.setattr(sources, 'resolved_ips', lambda host: ['93.184.216.34'])
    monkeypatch.setattr(sources, 'validate_url', lambda url, resolve=None: validate_url(url, resolve or (lambda host: ['127.0.0.1'] if host == '127.0.0.1' else ['93.184.216.34'])))
    targets = []
    class Socket:
        def close(self): pass
    monkeypatch.setattr(sources.socket, 'create_connection', lambda target, **kw: (targets.append(target) or Socket()))
    class Response:
        status = 302
        def getheader(self, name, default=None): return 'http://127.0.0.1/private' if name == 'Location' else default
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(sources.http.client, 'HTTPConnection', Connection)
    with pytest.raises(AppError): public_read('http://example.com')
    assert targets == [('93.184.216.34', 80)]


@pytest.mark.anyio
async def test_tavily_only_configuration_no_supplier_fallback(wire):
    adapter = Sources(Settings(_env_file=None, tavily_api_key='', jina_api_key='legacy-key'))
    with pytest.raises(AppError, match='检索服务'): await adapter.search('HTTP')
    assert not wire['calls']
    adapter = Sources(settings(jina_api_key=''))
    result = await adapter.search('HTTP')
    assert result and all(s['supplement'] for s in result)
    assert len(wire['calls']) == 1 and wire['calls'][0]['url'].endswith('/search')
    wire['status'] = 429
    with pytest.raises(AppError): await adapter.search('HTTP')
    assert len(wire['calls']) == 2 and all('tavily.com' in c['url'] for c in wire['calls'])


@pytest.mark.anyio
@pytest.mark.parametrize('inline', [False, True])
@pytest.mark.parametrize('automatic', [False, True])
async def test_video_selects_public_chinese_caption_and_applies_slice(monkeypatch, inline, automatic):
    import app.materials.sources as sources
    import yt_dlp
    monkeypatch.setattr(sources, 'validate_url', lambda url: url)
    monkeypatch.setattr(sources, 'public_read', lambda *args: ('https://captions.example.com', b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nFirst\n\n00:00:03.000 --> 00:00:05.000\nSecond\n', 'text/vtt'))
    class YDL:
        def __init__(self, options):
            assert options['skip_download'] and not options['usenetrc']
            assert options['writesubtitles'] and options['writeautomaticsub']
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download):
            assert not download
            track = {'ext':'srt','data':'1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n2\n00:00:03,000 --> 00:00:05,000\nSecond\n'} if inline else {'ext':'vtt','url':'https://captions.example.com'}
            tracks = {'subtitles':{'en':[{'ext':'vtt','url':'https://captions.example.com/english'}]},'automatic_captions':{'zh-CN':[track]}} if automatic else {'subtitles':{'zh-CN':[track]}}
            return {'title':'公开课程', 'duration':10, **tracks}
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', YDL)
    result = await Sources(Settings()).video('https://www.bilibili.com/video/BV1test', 2, 5)
    assert result['caption_kind'] == ('自动字幕' if automatic else '人工字幕')
    assert result['segments'][0]['text'] == 'Second' and result['segments'][0]['start'] == 3
    with pytest.raises(AppError): await Sources(Settings()).video('https://evil.example/video', 0, 5)
