"""Fenced, bounded MySQL jobs. Every publication owns one database transaction."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import and_, or_, select
from ..errors import AppError
from ..accounts.database import User, Operation
from .database import Job, Checkpoint, Document, PublishedResult
from .repository import KnowledgeRepository


@dataclass(frozen=True)
class Claim:
    id: str
    user_id: str
    kind: str
    operation_id: str
    document_id: str | None
    owner: str
    fence: int
    attempts: int
    deadline_at: datetime
    payload: dict
    budget: dict


class DurableJobs(KnowledgeRepository):
    def processed_result(self, claim):
        with self.database.session() as session:
            self.accounts._user(session,claim.user_id)
            row = self._owned_job(session,claim.user_id,claim.id)
            if row.operation_id != claim.operation_id: raise AppError('NOT_FOUND','操作不存在',404)
            return deepcopy(self._public_job_data(session,row)['result']) if row.status == 'succeeded' else None

    def _public_job_data(self, session, row):
        result = self.job_data(row)
        if row.kind == 'quiz' and row.status == 'succeeded':
            from ..accounts.database import Attempt
            from ..accounts.repository import serialize
            attempt = session.get(Attempt,row.result.get('id')) if row.result and row.result.get('id') else None
            result['result'] = serialize(attempt) if attempt and attempt.user_id == row.user_id else None
            if result['result'] is None:
                result['error_code'],result['message'] = 'KNOWLEDGE_RESULT_DELETED','对应学习记录已删除，不会重新生成'
        return result

    def _release_ai(self, session, row):
        if not row.ai_operation_id: return
        user = session.get(User,row.user_id)
        if user is None: return
        quota = self.accounts._quota(session,user.identity)
        operation = session.get(Operation,row.ai_operation_id)
        if operation and operation.user_id == row.user_id:
            if operation.status != 'succeeded':
                operation.status = 'succeeded' if row.status == 'succeeded' else 'failed'
                operation.stage = operation.status
                operation.result = deepcopy(row.result) if row.status == 'succeeded' else None
                operation.error_code = None if row.status == 'succeeded' else row.error_code
        if quota.busy_id == row.ai_operation_id: quota.busy_id, quota.busy_until = None, 0

    def _owned_job(self, session, uid, jid, *, lock=False):
        query = select(Job).where(Job.id == jid, Job.user_id == uid)
        if lock: query = query.with_for_update().execution_options(populate_existing=True)
        row = session.scalar(query)
        if row is None: raise AppError('NOT_FOUND', '知识库任务不存在', 404)
        return row

    def _terminal(self, session, row, code, message):
        row.status, row.stage, row.error_code, row.message = 'failed', 'failed', code, message[:300]
        row.owner, row.lease_until, row.retry_after_seconds = None, None, 0
        self._release_ai(session,row)
        if row.document_id and row.kind in ('import', 'reindex'):
            document = session.get(Document, row.document_id)
            if document and not document.active_revision_id and document.deleted_at is None:
                document.status = 'failed'

    def _expire(self, session, row):
        if row.status not in ('running', 'queued'): return
        if row.deadline_at <= self.now():
            self._terminal(session, row, 'KNOWLEDGE_JOB_EXPIRED', '任务已超过原定期限，请重新发起操作')
        elif row.status == 'queued' and (self.now()-row.created_at).total_seconds() > self.config.queue_timeout_seconds:
            self._terminal(session, row, 'KNOWLEDGE_QUEUE_TIMEOUT', '排队时间过长，请检查执行器后重试')

    def get(self, uid, jid):
        with self.database.session() as session:
            self.accounts._user(session, uid, True)
            row = self._owned_job(session, uid, jid, lock=True)
            self._expire(session, row)
            return self._public_job_data(session,row)

    def lookup(self, uid, kind, key):
        with self.database.session() as session:
            self.accounts._user(session,uid,True)
            row = session.scalar(select(Job).where(Job.user_id == uid,Job.kind == kind,Job.key == key).with_for_update())
            if row is None: raise AppError('NOT_FOUND','尚未找到该提交，可刷新资料列表或用原标识重试',404)
            self._expire(session,row)
            return self._public_job_data(session,row)

    def claim(self, owner):
        now = self.now()
        eligible = or_(and_(Job.status == 'queued', or_(Job.lease_until.is_(None), Job.lease_until <= now)),
                       and_(Job.status == 'running', or_(Job.lease_until.is_(None), Job.lease_until <= now)))
        with self.database.session() as session:
            candidates = list(session.execute(select(Job.id,Job.user_id).where(eligible)
                              .order_by(Job.priority,Job.created_at,Job.id).limit(100)))
        # Match the core quota -> user -> job lock order, including expiry cleanup.
        for jid, uid in candidates:
            with self.database.session() as session:
                try: self.accounts._user(session,uid,True)
                except AppError as error:
                    if error.code == 'AUTH_REQUIRED': continue
                    raise
                row = session.scalar(select(Job).where(Job.id == jid,eligible)
                                     .with_for_update(skip_locked=True).execution_options(populate_existing=True))
                if row is None: continue
                self._expire(session, row)
                if row.status == 'failed': continue
                if row.attempts >= self.config.job_max_attempts:
                    self._terminal(session, row, 'KNOWLEDGE_RETRY_LIMIT', '任务恢复次数已用完，请重新发起操作')
                    continue
                if row.document_id:
                    document = session.get(Document, row.document_id)
                    if document is None or document.deleted_at is not None:
                        self._terminal(session, row, 'KNOWLEDGE_DOCUMENT_DELETED', '原资料已删除，任务无法继续')
                        continue
                row.owner, row.fence, row.attempts = owner, row.fence+1, row.attempts+1
                row.status = 'running'
                row.stage = row.stage if row.stage not in ('queued', 'failed') else 'starting'
                row.lease_until = min(now+timedelta(seconds=self.config.lease_seconds), row.deadline_at)
                row.retry_after_seconds = 0
                session.flush()
                return Claim(row.id, row.user_id, row.kind, row.operation_id, row.document_id, owner, row.fence,
                             row.attempts, row.deadline_at, deepcopy(row.payload), deepcopy(row.budget))
        return None

    def _active(self, session, claim, *, validate_scope=True):
        self.accounts._user(session, claim.user_id, True)
        row = self._owned_job(session, claim.user_id, claim.id, lock=True)
        if (row.owner != claim.owner or row.fence != claim.fence or row.status != 'running'
                or row.deadline_at <= self.now() or row.lease_until is None or row.lease_until <= self.now()):
            raise AppError('KNOWLEDGE_JOB_STALE', '任务已取消、过期或交由新的执行器处理', 409)
        if validate_scope and row.document_id:
            self._document(session, row.user_id, row.document_id)
        if validate_scope and row.payload.get('documents'):
            self.validate_documents(row.user_id,row.payload['documents'],session=session)
        return row

    def heartbeat(self, claim):
        with self.database.session() as session:
            row = self._active(session, claim)
            row.lease_until = min(self.now()+timedelta(seconds=self.config.lease_seconds), row.deadline_at)

    def advance(self, claim, stage, progress):
        if type(progress) is not int or not 0 <= progress < 100:
            raise ValueError('Only successful publication can set progress to 100')
        with self.database.session() as session:
            row = self._active(session, claim)
            row.stage, row.progress = stage, max(row.progress, progress)

    def checkpoint(self, claim, name, content, *, stage, progress):
        if not 0 <= progress < 100: raise ValueError('Invalid checkpoint progress')
        with self.database.session() as session:
            row = self._active(session, claim)
            checkpoint = session.get(Checkpoint, (row.operation_id, name))
            if checkpoint is None:
                session.add(Checkpoint(operation_id=row.operation_id, name=name, user_id=row.user_id, content=deepcopy(content)))
            else:
                checkpoint.content, checkpoint.updated_at = deepcopy(content), self.now()
            row.stage, row.progress = stage, max(row.progress, progress)

    def read_checkpoint(self, claim, name):
        with self.database.session() as session:
            row = self._active(session, claim)
            checkpoint = session.get(Checkpoint, (row.operation_id, name))
            return deepcopy(checkpoint.content) if checkpoint and checkpoint.user_id == row.user_id else None

    def consume(self, claim, bucket, amount, limit):
        if type(amount) is not int or amount <= 0 or type(limit) is not int or limit < 1:
            raise ValueError('Invalid server budget reservation')
        with self.database.session() as session:
            row = self._active(session, claim)
            budget = dict(row.budget)
            if budget.get(bucket, 0)+amount > limit:
                raise AppError('KNOWLEDGE_BUDGET_EXHAUSTED', '本次任务调用预算已用完，请缩小范围或补充资料', 429)
            budget[bucket] = budget.get(bucket, 0)+amount
            row.budget = budget
            return limit-budget[bucket]

    def complete(self, claim, publish):
        with self.database.session() as session:
            self.accounts._user(session, claim.user_id, True)
            row = self._owned_job(session, claim.user_id, claim.id, lock=True)
            if row.owner == claim.owner and row.fence == claim.fence and row.status == 'succeeded':
                return deepcopy(row.result)
            row = self._active(session, claim)
            old = session.get(PublishedResult, row.operation_id)
            if old is not None:
                if old.user_id != row.user_id: raise AppError('NOT_FOUND', '操作结果不存在', 404)
                result = deepcopy(old.result)
            else:
                result = publish(session, row)
                session.add(PublishedResult(operation_id=row.operation_id, user_id=row.user_id, kind=row.kind, result=deepcopy(result)))
            row.status, row.stage, row.progress = 'succeeded', 'succeeded', 100
            row.result, row.error_code, row.message = deepcopy(result), None, None
            row.retry_after_seconds, row.lease_until = 0, None
            self._release_ai(session,row)
            session.flush()
            return deepcopy(result)

    def fail(self, claim, code, message, *, recoverable=False):
        with self.database.session() as session:
            row = self._active(session, claim,validate_scope=False)
            if recoverable and row.attempts < self.config.job_max_attempts:
                row.status, row.stage = 'queued', 'queued'
                row.error_code, row.message = code, message[:300]
                row.owner, row.lease_until = None, None
                self._release_ai(session,row)
            else:
                self._terminal(session, row, code, message)

    def yield_job(self, claim):
        """A completed small batch yields its slot without spending a recovery attempt."""
        with self.database.session() as session:
            row = self._active(session,claim)
            if row.kind not in ('import','reindex'): raise ValueError('Only index batches may yield')
            row.status, row.owner, row.lease_until = 'queued', None, None
            row.attempts = max(0,row.attempts-1)

    def cancel(self, uid, jid):
        with self.database.session() as session:
            self.accounts._user(session, uid, True)
            row = self._owned_job(session, uid, jid, lock=True)
            self._expire(session, row)
            if row.status in ('queued', 'running'):
                row.status, row.stage = 'cancelled', 'cancelled'
                row.error_code, row.message = 'KNOWLEDGE_JOB_CANCELLED', '已取消处理，已经发生的服务调用仍计入用量'
                row.owner, row.lease_until, row.retry_after_seconds = None, None, 0
                self._release_ai(session,row)
                if row.document_id and row.kind in ('import', 'reindex'):
                    document = session.get(Document, row.document_id)
                    if document and not document.active_revision_id and document.deleted_at is None:
                        document.status = 'cancelled'
            return self.job_data(row)

    def retry(self, uid, jid, key):
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise AppError('INVALID_INPUT', '操作标识不正确', 422)
        with self.database.session() as session:
            self.accounts._user(session, uid, True)
            old = self._owned_job(session, uid, jid, lock=True)
            prior = session.scalar(select(Job).where(Job.user_id == uid, Job.kind == old.kind, Job.key == key))
            if prior:
                if prior.operation_id != old.operation_id or prior.parent_id != old.id:
                    raise AppError('IDEMPOTENCY_CONFLICT', '重试标识已用于其他操作', 409)
                return self.job_data(prior)
            if old.status in ('queued', 'running', 'succeeded'):
                self._expire(session, old)
                return self.job_data(old)
            related = list(session.scalars(select(Job).where(Job.user_id == uid, Job.operation_id == old.operation_id)))
            active = next((j for j in related if j.status in ('queued', 'running')), None)
            if active: return self.job_data(active)
            if old.deadline_at <= self.now():
                raise AppError('KNOWLEDGE_JOB_EXPIRED', '原任务期限已到，请重新发起操作', 409)
            attempts = max(j.attempts for j in related)
            if attempts >= self.config.job_max_attempts or len(related) >= self.config.job_max_attempts:
                raise AppError('KNOWLEDGE_RETRY_LIMIT', '本次操作恢复次数已用完，请重新发起', 409)
            if old.document_id:
                document = self._document(session, uid, old.document_id, lock=True)
                if not document.active_revision_id: document.status = 'processing'
            budget = {}
            for row in related:
                for name, value in row.budget.items():
                    budget[name] = max(budget.get(name, 0), value)
            row = Job(id=str(uuid4()), user_id=uid, kind=old.kind, key=key, digest=old.digest,
                      operation_id=old.operation_id, ai_operation_id=old.ai_operation_id, parent_id=old.id,
                      document_id=old.document_id, payload=deepcopy(old.payload), budget=budget,
                      deadline_at=old.deadline_at, attempts=attempts, progress=max(j.progress for j in related),
                      priority=old.priority, created_at=self.now())
            session.add(row)
            session.flush()
            return self.job_data(row)
