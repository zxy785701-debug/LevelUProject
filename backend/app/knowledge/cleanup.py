"""Deletion facts commit first; durable outbox effects remain retryable after cascades."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import logging
from uuid import uuid4,uuid5,NAMESPACE_URL
from sqlalchemy import select,delete,or_,inspect
from ..accounts.database import User
from ..errors import AppError
from .database import Document,Revision,Chunk,Job,Cleanup,EmbeddingCache,Checkpoint,PublishedResult
from .files import FileStore
from .jobs import DurableJobs

logger = logging.getLogger(__name__)


def record_account_cleanup(session, uid):
    # Preserve the old core account API before the optional additive migration.
    if not inspect(session.connection()).has_table('knowledge_cleanup_outbox'): return
    profiles = set(session.scalars(select(Revision.profile).join(Document,Revision.document_id == Document.id).where(Document.user_id == uid)))
    profiles.update(session.scalars(select(EmbeddingCache.profile).where(EmbeddingCache.user_id == uid)))
    session.add(Cleanup(id=str(uuid4()),user_id=uid,payload={'kind':'account','profiles':sorted(profiles)}))


def clear_deleted_learning_result(session, uid, aid):
    if not inspect(session.connection()).has_table('knowledge_jobs'): return
    jobs = list(session.scalars(select(Job).where(Job.user_id == uid,Job.kind == 'quiz',Job.result['id'].as_string() == aid).with_for_update()))
    for job in jobs:
        job.result,job.payload = None,{'history_deleted':True}
        job.error_code,job.message = 'KNOWLEDGE_RESULT_DELETED','对应学习记录已删除，不会重新生成'
        session.execute(delete(Checkpoint).where(Checkpoint.operation_id == job.operation_id))
        published = session.get(PublishedResult,job.operation_id)
        if published and published.user_id == uid: published.result = {}


class LibraryManagement(DurableJobs):
    @staticmethod
    def _deletion_data(row):
        return {'deleted':True,'cleanup':{'kind':'knowledge_cleanup','id':row.id,'status':row.status} if row else None}

    def delete_document(self, uid, did):
        with self.database.session() as session:
            self.accounts._user(session,uid,True)
            document = session.scalar(select(Document).where(Document.id == did,Document.user_id == uid).with_for_update())
            if document is None: raise AppError('NOT_FOUND','知识库资料不存在',404)
            if document.deleted_at is not None:
                cleanup = session.scalar(select(Cleanup).where(Cleanup.user_id == uid,Cleanup.payload['kind'].as_string() == 'document',
                    Cleanup.payload['document_id'].as_string() == did).order_by(Cleanup.created_at.desc()).limit(1))
                return self._deletion_data(cleanup)
            document.deleted_at,document.status,document.updated_at = self.now(),'deleted',self.now()
            jobs = list(session.scalars(select(Job).where(Job.document_id == did,Job.user_id == uid).with_for_update()))
            paths = sorted({j.payload['file_path'] for j in jobs if j.payload.get('file_path')})
            for job in jobs:
                if job.status in ('queued','running'):
                    job.status,job.stage,job.error_code,job.message = 'cancelled','cancelled','KNOWLEDGE_DOCUMENT_DELETED','原资料已删除'
                    job.owner,job.lease_until = None,None
                    self._release_ai(session,job)
            profiles = set(session.scalars(select(Revision.profile).where(Revision.document_id == did)))
            cleanup = Cleanup(id=str(uuid4()),user_id=uid,created_at=self.now(),payload={
                'kind':'document','document_id':did,'profiles':sorted(profiles),'file_paths':paths})
            session.add(cleanup)
            session.flush()
            return self._deletion_data(cleanup)

    def cleanup_status(self, uid, cid):
        with self.database.session() as session:
            self.accounts._user(session,uid)
            row = session.scalar(select(Cleanup).where(Cleanup.id == cid,Cleanup.user_id == uid))
            if row is None: raise AppError('NOT_FOUND','清理记录不存在',404)
            return {'kind':'knowledge_cleanup','id':row.id,'status':row.status,'attempts':row.attempts,'error_code':row.error_code}


class CleanupManager(DurableJobs):
    def __init__(self, accounts, config, index):
        super().__init__(accounts,config)
        self.index, self.owner = index,str(uuid4())

    def collect_garbage(self):
        count = 0
        with self.database.session() as session:
            candidates = list(session.execute(select(Revision.id,Revision.document_id,Revision.profile,Document.user_id,Document.active_revision_id)
                .join(Document,Document.id == Revision.document_id).where(Revision.status == 'staging',
                Revision.created_at < self.now()-timedelta(hours=24),Document.deleted_at.is_(None)).limit(100)))
            for rid,did,profile,uid,active_rid in candidates:
                live = session.scalar(select(Job.id).where(Job.document_id == did,Job.status.in_(['queued','running']),Job.deadline_at > self.now()).limit(1))
                identity = str(uuid5(NAMESPACE_URL,'levelup-knowledge-gc:'+rid))
                if live or session.get(Cleanup,identity): continue
                jobs = session.scalars(select(Job).where(Job.document_id == did,Job.user_id == uid)) if active_rid is None else []
                paths = sorted({j.payload['file_path'] for j in jobs if j.payload.get('file_path')})
                session.add(Cleanup(id=identity,user_id=uid,payload={'kind':'revision','document_id':did,'revision_id':rid,'profiles':[profile],'file_paths':paths}))
                count += 1
        return count

    def _claim(self):
        with self.database.session() as session:
            row = session.scalar(select(Cleanup).where(Cleanup.status.in_(['queued','running']),
                or_(Cleanup.lease_until.is_(None),Cleanup.lease_until <= self.now()))
                .order_by(Cleanup.created_at,Cleanup.id).with_for_update(skip_locked=True).limit(1))
            if row is None: return None
            row.status,row.owner,row.fence,row.attempts = 'running',self.owner,row.fence+1,row.attempts+1
            row.lease_until = self.now()+timedelta(seconds=self.config.lease_seconds)
            return row.id,row.user_id,row.fence,deepcopy(row.payload)

    def process_one(self):
        claim = self._claim()
        if claim is None: return False
        cid,uid,fence,payload = claim
        try:
            with self.database.session() as session:
                if payload['kind'] == 'account':
                    if session.get(User,uid): raise AppError('KNOWLEDGE_CLEANUP_CONFLICT','账号仍有效，清理已停止',409)
                else:
                    document = session.get(Document,payload['document_id'])
                    if document and (document.user_id != uid or
                            payload['kind'] == 'document' and document.deleted_at is None or
                            payload['kind'] == 'revision' and document.active_revision_id == payload['revision_id']):
                        raise AppError('KNOWLEDGE_CLEANUP_CONFLICT','资料状态已变化，清理已停止',409)
            self.index.remove(uid,payload)
            store = FileStore(self.config.storage_root)
            if payload['kind'] == 'account': store.delete_user(uid)
            else:
                for path in payload.get('file_paths',[]): store.delete(uid,path)
            with self.database.session() as session:
                row = session.scalar(select(Cleanup).where(Cleanup.id == cid).with_for_update())
                if row.owner != self.owner or row.fence != fence or row.status != 'running': return True
                if payload['kind'] != 'account':
                    revisions = list(session.scalars(select(Revision).where(Revision.document_id == payload['document_id'],
                        *([Revision.id == payload['revision_id']] if payload['kind'] == 'revision' else []))))
                    for revision in revisions:
                        hashes = list(session.scalars(select(Chunk.content_hash).where(Chunk.revision_id == revision.id)))
                        if hashes: session.execute(delete(EmbeddingCache).where(EmbeddingCache.user_id == uid,EmbeddingCache.content_hash.in_(hashes)))
                        session.execute(delete(Chunk).where(Chunk.revision_id == revision.id))
                        revision.text,revision.segments,revision.status = '',[],'deleted'
                row.status,row.lease_until,row.error_code = 'succeeded',None,None
        except Exception:
            logger.warning('cleanup_failed outbox=%s kind=%s error_code=KNOWLEDGE_CLEANUP_FAILED',cid,payload.get('kind'))
            with self.database.session() as session:
                row = session.scalar(select(Cleanup).where(Cleanup.id == cid).with_for_update())
                if row and row.owner == self.owner and row.fence == fence:
                    row.status,row.error_code = 'queued','KNOWLEDGE_CLEANUP_FAILED'
                    row.lease_until = self.now()+timedelta(seconds=min(2**min(row.attempts,10),900))
        return True
