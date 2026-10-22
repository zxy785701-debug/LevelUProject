"""Safe extraction and exact offsets into persisted, canonical extracted text."""
from copy import deepcopy
import hashlib
import re
from ..errors import AppError
from ..materials.parsers import parse_document
from .files import validate_upload

PARSER_VERSION = 'knowledge-parser-v1'
SPLITTER_VERSION = 'knowledge-splitter-v1'


def canonical_content(content, *, max_chars):
    result = deepcopy(content)
    segments, pieces, offset = [], [], 0
    for block, original in enumerate(content.get('segments',[])):
        text = original.get('text','').strip()
        if not text: continue
        if pieces: offset += 2
        segment = {**original,'text':text,'block':block+1,'start_index':offset,'end_index':offset+len(text)}
        segments.append(segment)
        pieces.append(text)
        offset += len(text)
    if not segments:
        raise AppError('NO_READABLE_CONTENT','未找到可读取文字；扫描件需要先转换为文字版',422)
    if offset > max_chars:
        raise AppError('MATERIAL_TOO_LARGE','提取正文超过十万字符，请拆分资料后添加',422)
    result.update(text='\n\n'.join(pieces),segments=segments,parser_version=PARSER_VERSION)
    return result


def parse_file(name, data, settings):
    name, kind = validate_upload(name,data,settings.material_max_bytes)
    if kind in ('md','markdown','txt'):
        # Reuse the existing text safety/encoding checks; retain the original whole
        # text rather than inheriting the legacy 4000-character preview segmentation.
        parsed = parse_document(name if kind == 'txt' else name+'.txt',data,
            max_bytes=settings.material_max_bytes,max_chars=settings.material_max_chars,max_pages=settings.material_max_pages)
        for encoding in ('utf-8-sig','gb18030'):
            try:
                text = data.decode(encoding).replace('\r\n','\n').replace('\r','\n').strip()
                break
            except UnicodeDecodeError: pass
        parsed.update(title=name,filename=name,source_type=kind,segments=[{'text':text}])
    else:
        parsed = parse_document(name,data,max_bytes=settings.material_max_bytes,
                                max_chars=settings.material_max_chars,max_pages=settings.material_max_pages)
    return canonical_content(parsed,max_chars=settings.material_max_chars)


def _markdown_sections(text):
    from langchain_text_splitters import MarkdownHeaderTextSplitter
    headers = [('#'*n,f'h{n}') for n in range(1,7)]
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers,strip_headers=False)
    # The header splitter normalizes whitespace. Map its header metadata onto raw
    # line boundaries so code, tables and citation offsets retain original text.
    boundaries, stack, offset, fence = [(0,[])], {}, 0, None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(' ')
        marker = re.match(r'^(`{3,}|~{3,})',stripped) if len(line)-len(stripped) <= 3 else None
        if marker:
            token = marker[1]
            if fence is None: fence = token
            elif token[0] == fence[0] and len(token) >= len(fence): fence = None
        elif fence is None and re.match(r'^ {0,3}#{1,6}(?:\s|$)',line):
            documents = splitter.split_text(line)
            metadata = documents[0].metadata if documents else {}
            if metadata:
                key, value = next(iter(metadata.items()))
                level = int(key[1:])
                stack = {k:v for k,v in stack.items() if k < level}
                stack[level] = value
                path = [stack[k] for k in sorted(stack)]
                if offset == boundaries[-1][0]: boundaries[-1] = (offset,path)
                else: boundaries.append((offset,path))
        offset += len(line)
    for i,(start,path) in enumerate(boundaries):
        end = boundaries[i+1][0] if i+1 < len(boundaries) else len(text)
        if text[start:end].strip(): yield start,end,path


def split_content(content, revision_id, config):
    from langchain_core.documents import Document as TextDocument
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    text = content['text']
    groups = []
    if content['source_type'] in ('md','markdown'):
        for start,end,path in _markdown_sections(text):
            groups.append(TextDocument(page_content=text[start:end],metadata={'base_index':start,'header_path':path}))
    else:
        for segment in content['segments']:
            location = {k:segment[k] for k in ('page','block','url','retrieved_at','truncated','source_chars') if k in segment}
            groups.append(TextDocument(page_content=segment['text'],metadata={**location,'base_index':segment['start_index'],'header_path':[]}))
    splitter = RecursiveCharacterTextSplitter(chunk_size=config.chunk_size,chunk_overlap=config.chunk_overlap,
        separators=['\n\n','\n','。','！','？','；','，','、',' ','.',',','\u200b',''],
        keep_separator=True,add_start_index=True,strip_whitespace=False)
    result = []
    from .embeddings import safe_text_parts
    pieces = []
    for piece in splitter.split_documents(groups):
        # Character sizing is independent of the provider's conservative byte bound.
        offset = 0
        for part in safe_text_parts(piece.page_content):
            metadata = {**piece.metadata,'start_index':piece.metadata['start_index']+offset}
            pieces.append(TextDocument(page_content=part,metadata=metadata))
            offset += len(part)
    for piece in pieces:
        if not piece.page_content.strip(): continue
        location = dict(piece.metadata)
        start = location.pop('base_index')+location.pop('start_index')
        end = start+len(piece.page_content)
        if start < 0 or text[start:end] != piece.page_content:
            raise AppError('KNOWLEDGE_LOCATION_INVALID','分块无法定位原文，请重新添加资料',422)
        location.update(start_index=start,end_index=end,line_start=text.count('\n',0,start)+1,
                        line_end=text.count('\n',0,end)+1,splitter_version=SPLITTER_VERSION)
        content_hash = hashlib.sha256(piece.page_content.encode()).hexdigest()
        position = len(result)
        cid = hashlib.sha256(f'{revision_id}:{position}:{start}:{content_hash}'.encode()).hexdigest()
        result.append({'id':cid,'position':position,'text':piece.page_content,'content_hash':content_hash,'location':location})
    if not result: raise AppError('NO_READABLE_CONTENT','没有可建立索引的文字片段',422)
    return result
