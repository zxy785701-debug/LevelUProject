"""One index batch per scheduler turn; only a verified revision can become active."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from uuid import uuid4
from sqlalchemy import select
from ..errors import AppError
from .database import Job,Document,Revision,Checkpoint
from .embeddings import BailianEmbeddings
from .importing import ImportPipeline


class ImportIndexer(ImportPipeline):
    def __init__(self, accounts, config, index, *, embedding_factory=None):
        super().__init__(accounts,config)
        self.index = index
        self.embedding_factory = embedding_factory or (lambda claim:BailianEmbeddings(accounts,config,claim))

    def submit_reindex(self, uid, key, did):
        if not isinstance(key,str) or not 1 <= len(key) <= 128: raise AppError('INVALID_INPUT','操作标识不正确',422)
        with self.database.session() as session:
            user = self.accounts._user(session,uid,True)
            old = session.scalar(select(Job).where(Job.user_id == uid,Job.kind == 'reindex',Job.key == key))
            if old:
                if old.document_id != did: raise AppError('IDEMPOTENCY_CONFLICT','重建标识已用于其他资料',409)
                return self.job_data(old)
            document = self._document(session,uid,did,lock=True)
            if not document.active_revision_id:
                raise AppError('DOCUMENT_NOT_READY','请先完成原导入或重试失败任务',409)
            active = session.scalar(select(Job).where(Job.user_id == uid,Job.document_id == did,Job.status.in_(['queued','running'])))
            if active: return self.job_data(active)
            revision = session.get(Revision,document.active_revision_id)
            usage = self._usage(session,user.identity)
            if usage.imports >= self.config.import_daily_limit:
                raise AppError('KNOWLEDGE_IMPORT_DAILY_LIMIT','今天的知识库导入或重建次数已用完',429)
            content = {**deepcopy(document.source),**deepcopy(revision.manifest.get('source',{})),'title':document.title,
                'source_type':document.source_type,'segments':deepcopy(revision.segments) or [{'text':revision.text}]}
            row = Job(id=str(uuid4()),user_id=uid,kind='reindex',key=key,
                digest=hashlib.sha256(json.dumps([did,revision.id,self.profile]).encode()).hexdigest(),operation_id=str(uuid4()),
                document_id=did,payload={'source':'material','material_content':content},
                deadline_at=self.now()+timedelta(seconds=self.config.import_timeout_seconds),created_at=self.now())
            session.add(row)
            usage.imports += 1
            session.flush()
            return self.job_data(row)

    def process(self, claim):
        parsed = self.parse(claim)
        chunks = self.split(claim,parsed)
        batch_size = self.config.embedding_batch_size
        for start in range(0,len(chunks),batch_size):
            batch = chunks[start:start+batch_size]
            name = f'vectors:{start//batch_size}'
            checkpoint = self.read_checkpoint(claim,name)
            if checkpoint:
                try:
                    self.index.verify(claim,parsed['revision_id'],[c['id'] for c in batch],complete=False)
                    continue
                except AppError as error:
                    if error.code != 'KNOWLEDGE_INDEX_INCOMPLETE': raise
            vectors = self.embedding_factory(claim).embed_documents([c['text'] for c in batch])
            self.index.upsert(claim,parsed['revision_id'],batch,vectors)
            self.index.verify(claim,parsed['revision_id'],[c['id'] for c in batch],complete=False)
            self.checkpoint(claim,name,{'ids':[c['id'] for c in batch]},stage='embedding',
                            progress=35+int(50*(start+len(batch))/len(chunks)))
            if start+len(batch) < len(chunks):
                self.yield_job(claim)
                return None
        return self.activate(claim,parsed,chunks)

    def activate(self, claim, parsed, chunks):
        count = self.index.verify(claim,parsed['revision_id'],[c['id'] for c in chunks])
        def publish(session,row):
            document = self._document(session,row.user_id,row.document_id,lock=True)
            revision = session.get(Revision,parsed['revision_id'])
            if (revision is None or revision.document_id != document.id or revision.profile != self.profile
                    or revision.status != 'staging' or revision.manifest['chunk_ids'] != [c['id'] for c in chunks]):
                raise AppError('KNOWLEDGE_INDEX_INCOMPLETE','版本清单已变化，请重试处理',409)
            old = session.get(Revision,document.active_revision_id) if document.active_revision_id else None
            if old: old.status = 'retired'
            manifest = dict(revision.manifest)
            manifest['vector_count'] = count
            revision.manifest, revision.status = manifest,'ready'
            document.active_revision_id,document.status,document.updated_at = revision.id,'ready',self.now()
            document.title = parsed.get('title',document.title)[:180]
            document.source = {k:deepcopy(parsed[k]) for k in ('filename','url','retrieved_at','published_at','truncated','source_chars') if k in parsed and parsed[k] is not None}
            return {'document_id':document.id,'revision_id':revision.id,'version':revision.number}
        return self.complete(claim,publish)
