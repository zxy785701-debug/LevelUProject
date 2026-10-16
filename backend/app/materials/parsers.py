import html
import io
import ipaddress
import json
import re
import socket
import zipfile
from pathlib import PurePath
from urllib.parse import urlsplit, urlunsplit
from ..errors import AppError


def fail(message, code='MATERIAL_INVALID', status=422):
    raise AppError(code, message, status)


def segments_checked(title, segments, max_chars=100000, **meta):
    segments = [{**s, 'text': s['text'].strip()} for s in segments if s['text'].strip()]
    if not segments: fail('未找到可读取文字；扫描件需要文字版，视频可粘贴笔记', 'NO_READABLE_CONTENT')
    if sum(len(s['text']) for s in segments) > max_chars: fail('提取文字超出上限，请缩小学习范围', 'MATERIAL_TOO_LARGE')
    return {'title': title[:180], 'segments': [{**s, 'id': f's{i+1}'} for i, s in enumerate(segments)], **meta}


def page_numbers(pages, count, limit):
    if not pages:
        if count > limit: fail(f'全文超过 {limit} 页，请指定页码范围', 'PAGE_LIMIT')
        return list(range(1, count + 1))
    selected = []
    for part in pages.replace('–', '-').replace('，', ',').split(','):
        if not re.fullmatch(r'\s*\d+\s*(?:-\s*\d+\s*)?', part): fail('页码格式为 1-6 或 1,3-6', 'INVALID_RANGE')
        ends = [int(v) for v in part.split('-')]
        first, last = ends[0], ends[-1]
        if first < 1 or last < first or last > count or last-first+1 > limit: fail('页码超出文档或解析范围', 'INVALID_RANGE')
        selected.extend(range(first, last + 1))
    if len(set(selected)) != len(selected) or len(selected) > limit: fail('页码不可重复或超过页数上限', 'INVALID_RANGE')
    return sorted(selected)


def parse_document(name, data, pages=None, max_bytes=20*1024*1024, max_chars=100000, max_pages=200, max_expanded=50*1024*1024):
    if not data or len(data) > max_bytes: fail('文件为空或超过大小上限', 'MATERIAL_TOO_LARGE')
    name = PurePath(name.replace('\\', '/')).name
    extension = PurePath(name).suffix.lower()
    if extension not in ('.pdf', '.docx', '.txt'): fail('请选择文字版 PDF、DOCX 或 TXT；暂不支持 DOC', 'UNSUPPORTED_FORMAT')
    if pages and extension != '.pdf': fail('DOCX 和 TXT 没有固定页码，请选择全文', 'INVALID_RANGE')
    try:
        if extension == '.pdf':
            from pypdf import PdfReader
            if not data.startswith(b'%PDF-'): fail('文件内容不是 PDF')
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted: fail('请先解除 PDF 密码保护', 'ENCRYPTED_PDF')
            numbers = page_numbers(pages, len(reader.pages), max_pages)
            segments = []
            size = 0
            for number in numbers:
                page = reader.pages[number-1]
                content = page.get_contents()
                if content and len(content.get_data()) > max_expanded: fail('PDF 页内容过大，请缩小范围', 'MATERIAL_TOO_LARGE')
                text = page.extract_text() or ''
                size += len(text)
                if size > max_chars: fail('提取文字超出上限，请缩小学习范围', 'MATERIAL_TOO_LARGE')
                segments.append({'page': number, 'text': text})
        elif extension == '.docx':
            from docx import Document
            from docx.text.paragraph import Paragraph
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(v.file_size for v in z.infolist()) > max_expanded or len(z.infolist()) > 10000: fail('文档解压体积过大', 'MATERIAL_TOO_LARGE')
                if 'word/document.xml' not in z.namelist(): fail('文件内容不是 DOCX')
            doc = Document(io.BytesIO(data))
            segments = [{'text': block.text if isinstance(block, Paragraph) else '\n'.join(' | '.join(cell.text for cell in row.cells) for row in block.rows)} for block in doc.iter_inner_content()]
        else:
            if b'\x00' in data: fail('TXT 含有二进制内容')
            text = None
            for encoding in ('utf-8-sig', 'gb18030'):
                try: text = data.decode(encoding); break
                except UnicodeDecodeError: pass
            if text is None or re.search(r'[\x00-\x08\x0b\x0e-\x1f]', text): fail('TXT 编码或内容不正确')
            segments = [{'text': text[i:i+4000]} for i in range(0, len(text), 4000)]
        return segments_checked(name, segments, max_chars, source_type=extension[1:], filename=name, page_range=pages)
    except AppError:
        raise
    except Exception:
        fail('文档损坏或格式无法读取，请重新导出后上传')


def resolved_ips(host):
    return list({v[4][0] for v in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})


def validate_url(url, resolve=resolved_ips):
    try:
        if re.search(r'[\x00-\x20\\]', url) or len(url) > 2048: raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 80, 443): raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii')
        addresses = resolve(host)
        if not addresses or any(not ipaddress.ip_address(v).is_global for v in addresses): raise ValueError()
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '', parsed.query, ''))
    except (ValueError, UnicodeError, OSError):
        fail('请使用可公开访问的 HTTP/HTTPS 链接', 'INVALID_URL')


def seconds(value):
    parts = value.replace(',', '.').split(':')
    return sum(float(v) * 60**i for i, v in enumerate(reversed(parts)))


def caption_segments(data, extension, start=0, end=None):
    if start < 0 or (end is not None and end <= start): fail('片段起止时间不正确', 'INVALID_RANGE')
    cues = []
    if extension in ('json', 'json3'):
        raw = json.loads(data)
        if 'body' in raw: cues = [(v['from'], v['to'], v['content']) for v in raw['body']]
        else: cues = [(v.get('tStartMs', 0)/1000, (v.get('tStartMs', 0)+v.get('dDurationMs', 0))/1000, ''.join(s.get('utf8', '') for s in v.get('segs', []))) for v in raw.get('events', [])]
    else:
        for block in re.split(r'\n\s*\n', data.replace('\r', '')):
            match = re.search(r'([\d:.,]+)\s*-->\s*([\d:.,]+)[^\n]*\n(.*)', block, re.S)
            if match: cues.append((seconds(match[1]), seconds(match[2]), match[3]))
    result = []
    for a, b, text in cues:
        text = html.unescape(re.sub(r'<[^>]*>', '', text)).strip()
        if b <= start or (end is not None and a >= end) or not text: continue
        if result and result[-1]['text'] == text: continue
        result.append({'start': a, 'end': b, 'text': text})
    if not result: fail('该片段没有可读取字幕，可调整范围或粘贴笔记', 'NO_READABLE_CONTENT')
    return result
