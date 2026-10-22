"""Recoverable extraction and immutable staging; no active index is published here."""
import asyncio
from copy import deepcopy
import hashlib
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select,func
from ..errors import AppError
from ..materials.parsers import validate_url
from ..materials.sources import Sources
from .budgets import JobBudgets
from .database import Document,Revision,Chunk,Checkpoint
from .files import FileStore
from .parsing import parse_file,canonical_content,split_content,PARSER_VERSION,SPLITTER_VERSION


async def fetch_web(url, source, *, before_request=None):
    url = await asyncio.to_thread(validate_url,url,source.tools.resolve)
    content = await source.web(url,before_request=before_request)
    if not content.get('segments') or any(s.get('content_kind') != 'full_extract' for s in content['segments']):
        raise AppError('KNOWLEDGE_WEB_BODY_REQUIRED','未取得网页实际正文，请换公开链接或上传文档',422)
    result = canonical_content(content,max_chars=source.settings.material_max_chars)
    result.update(retrieved_at=content['segments'][0].get('retrieved_at'),
                  truncated=any(s.get('truncated') for s in content['segments']),
                  source_chars=max(s.get('source_chars',len(s['text'])) for s in content['segments']))
    return result


class ImportPipeline(JobBudgets):
    def _parsed_content(self, session, row, revision_id):
        revision = session.get(Revision,revision_id)
        if revision is None or revision.document_id != row.document_id or revision.profile != self.profile:
            raise AppError('KNOWLEDGE_PROFILE_CHANGED','索引配置已变化，请重新发起资料处理',409)
        return {**deepcopy(revision.manifest['source']),'revision_id':revision.id,
                'text':revision.text,'segments':deepcopy(revision.segments),'parser_version':revision.parser_version}

    def parse(self, claim, *, sources=None):
        with self.database.session() as session:
            row = self._active(session,claim)
            checkpoint = session.get(Checkpoint,(row.operation_id,'parsed'))
            if checkpoint: return self._parsed_content(session,row,checkpoint.content['revision_id'])
        self.advance(claim,'parsing',10)
        payload = claim.payload
        if payload['source'] == 'file':
            data = FileStore(self.config.storage_root).read(claim.user_id,payload['file_path'])
            if hashlib.sha256(data).hexdigest() != payload['sha256']:
                raise AppError('KNOWLEDGE_FILE_CHANGED','原文件校验不一致，请重新上传',409)
            content = parse_file(payload['filename'],data,self.accounts.settings)
        elif payload['source'] == 'material':
            content = canonical_content(payload['material_content'],max_chars=self.accounts.settings.material_max_chars)
        elif payload['source'] == 'web':
            async def before():
                self.consume(claim,'tool_calls',1,self.accounts.settings.retrieval_tool_call_limit)
                self.consume(claim,'page_attempts',1,self.accounts.settings.retrieval_max_page_attempts)
            content = asyncio.run(fetch_web(payload['url'],sources or Sources(self.accounts.settings),before_request=before))
        else:
            raise AppError('INVALID_INPUT','资料导入类型不正确',422)
        return self.save_parsed(claim,content)

    def save_parsed(self, claim, content):
        with self.database.session() as session:
            row = self._active(session,claim)
            checkpoint = session.get(Checkpoint,(row.operation_id,'parsed'))
            if checkpoint: return self._parsed_content(session,row,checkpoint.content['revision_id'])
            document = self._document(session,row.user_id,row.document_id,lock=True)
            sizes = session.execute(select(Document.id,func.max(func.char_length(Revision.text)))
                .join(Revision,Revision.document_id == Document.id).where(Document.user_id == row.user_id,
                Document.deleted_at.is_(None),Revision.status.in_(['ready','staging'])).group_by(Document.id))
            total = sum(size or 0 for did,size in sizes if did != document.id)+len(content['text'])
            if total > self.config.max_total_chars:
                raise AppError('KNOWLEDGE_TEXT_LIMIT','知识库正文总量已达上限，请删除不需要的资料后重试',429)
            number = (session.scalar(select(func.max(Revision.number)).where(Revision.document_id == document.id)) or 0)+1
            rid = str(uuid5(NAMESPACE_URL,'levelup-knowledge:'+row.operation_id))
            source = {k:deepcopy(v) for k,v in content.items() if k not in ('text','segments','revision_id')}
            revision = Revision(id=rid,document_id=document.id,number=number,profile=self.profile,text=content['text'],
                segments=deepcopy(content['segments']),manifest={'source':source},parser_version=PARSER_VERSION,splitter_version=SPLITTER_VERSION)
            session.add(revision)
            session.add(Checkpoint(operation_id=row.operation_id,name='parsed',user_id=row.user_id,content={'revision_id':rid}))
            row.stage,row.progress = 'parsed',max(row.progress,25)
            session.flush()
            return self._parsed_content(session,row,rid)

    def split(self, claim, parsed):
        rid = parsed['revision_id']
        with self.database.session() as session:
            row = self._active(session,claim)
            self._parsed_content(session,row,rid)
            checkpoint = session.get(Checkpoint,(row.operation_id,'split'))
            if checkpoint:
                chunks = session.scalars(select(Chunk).where(Chunk.revision_id == rid).order_by(Chunk.position))
                return [{'id':c.id,'position':c.position,'text':c.text,'content_hash':c.content_hash,'location':deepcopy(c.location)} for c in chunks]
        chunks = split_content(parsed,rid,self.config)
        with self.database.session() as session:
            row = self._active(session,claim)
            revision = session.get(Revision,rid)
            if revision is None or revision.document_id != row.document_id or revision.status != 'staging':
                raise AppError('KNOWLEDGE_JOB_STALE','暂存版本已不可修改',409)
            if session.get(Checkpoint,(row.operation_id,'split')):
                return chunks
            for chunk in chunks: session.add(Chunk(revision_id=rid,**chunk))
            manifest = dict(revision.manifest)
            manifest.update(chunk_ids=[c['id'] for c in chunks],chunk_count=len(chunks),
                            content_hash=hashlib.sha256(parsed['text'].encode()).hexdigest(),
                            chunks_hash=hashlib.sha256(''.join(c['content_hash'] for c in chunks).encode()).hexdigest())
            revision.manifest = manifest
            session.add(Checkpoint(operation_id=row.operation_id,name='split',user_id=row.user_id,content={'revision_id':rid,'chunk_count':len(chunks)}))
            row.stage,row.progress = 'split',max(row.progress,35)
        return chunks
