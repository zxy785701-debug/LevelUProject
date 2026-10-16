import json
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, delete
from ..accounts.database import Material, MaterialJob, PeriodReport, Operation, utcnow
from ..accounts.repository import digest, stamp
from ..errors import AppError


class Features:
    def __init__(self, accounts): self.accounts = accounts

    def _owned(self, s, model, uid, key):
        row = s.get(model, key)
        if row is None or row.user_id != uid: raise AppError('NOT_FOUND', '材料或报告不存在', 404)
        return row

    def job_data(self, row):
        return {k: getattr(row, k) for k in ('id', 'status', 'stage', 'material_id', 'preparation_id', 'error_code', 'message')}

    def create_job(self, uid, key, payload):
        hashed = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        with self.accounts.database.session() as s:
            u = self.accounts._user(s, uid, True)
            old = s.scalar(select(MaterialJob).where(MaterialJob.user_id == uid, MaterialJob.key == key))
            if old:
                if old.digest != hashed: raise AppError('IDEMPOTENCY_CONFLICT', '重复操作的参数不同', 409)
                return self.job_data(old), False
            q = self.accounts._quota(s, u.identity)
            if q.material_count >= self.accounts.settings.material_daily_limit: raise AppError('MATERIAL_DAILY_LIMIT', '今天的解析次数已用完，明天再来吧', 429)
            q.material_count += 1
            row = MaterialJob(id=str(uuid4()), user_id=uid, key=key, digest=hashed)
            s.add(row); s.flush()
            return self.job_data(row), True

    def job(self, uid, jid, stage=None, cancel=False, error=None, material=None):
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid, True)
            row = self._owned(s, MaterialJob, uid, jid)
            timeout = max(300, 2*self.accounts.settings.source_timeout_seconds + self.accounts.settings.model_timeout_seconds*self.accounts.settings.model_max_attempts + 60)
            if row.status == 'running' and row.created_at < utcnow()-timedelta(seconds=timeout):
                row.status, row.error_code, row.message = 'failed', 'OPERATION_EXPIRED', '解析中断或超时，请重新解析'
            if row.status == 'running':
                if cancel: row.status, row.message = 'cancelled', '已取消解析，输入仍保留'
                elif error: row.status, row.error_code, row.message = 'failed', error.code, error.message[:300]
                elif material:
                    mid = str(uuid4())
                    s.add(Material(id=mid, user_id=uid, content=material))
                    row.status, row.stage, row.material_id = 'succeeded', 'ready', mid
                elif stage: row.stage = stage
            return self.job_data(row)

    def material(self, uid, mid, referenced=False):
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid)
            row = self._owned(s, Material, uid, mid)
            if referenced: row.referenced = 1
            return {'id': row.id, **row.content, 'created_at': stamp(row.created_at), 'search_available': self.accounts.settings.tavily_available}

    def prepare_report(self, uid, snapshot):
        hashed = digest(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid, True)
            row = s.scalar(select(PeriodReport).where(PeriodReport.user_id == uid, PeriodReport.digest == hashed))
            if row is None:
                row = PeriodReport(id=str(uuid4()), user_id=uid, digest=hashed, snapshot=snapshot)
                s.add(row); s.flush()
            return self.report_data(row)

    def report_data(self, row):
        return {'id': row.id, 'status': row.status, 'snapshot': row.snapshot, 'content': row.content, 'attempts': row.attempts, 'error_code': row.error_code, 'created_at': stamp(row.created_at)}

    def _expire_report(self, s, row):
        if row.status not in ('running', 'pending'): return
        op = s.scalar(select(Operation).where(Operation.user_id == row.user_id, Operation.kind == 'period', Operation.attempt_id == row.id, Operation.status == 'running').order_by(Operation.created_at.desc()).limit(1))
        if not op and row.status == 'pending': return
        user = self.accounts._user(s, row.user_id)
        quota = self.accounts._quota(s, user.identity)
        if not op or quota.busy_id != op.id or quota.busy_until <= self.accounts.clock():
            row.status, row.error_code = 'failed', 'OPERATION_EXPIRED'
            if op:
                op.status, op.error_code = 'failed', 'OPERATION_EXPIRED'
                if quota.busy_id == op.id: quota.busy_id, quota.busy_until = None, 0

    def report(self, uid, rid, result=None, error=None):
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid, True)
            row = self._owned(s, PeriodReport, uid, rid)
            self._expire_report(s, row)
            if result is not None: row.content, row.status, row.error_code = result, 'succeeded', None
            if error: row.status, row.error_code = 'failed', error
            return self.report_data(row)

    def reports(self, uid):
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid, True)
            rows = list(s.scalars(select(PeriodReport).where(PeriodReport.user_id == uid).order_by(PeriodReport.created_at.desc()).limit(30)))
            for row in rows: self._expire_report(s, row)
            return [self.report_data(v) for v in rows]

    def cleanup(self):
        with self.accounts.database.session() as s:
            s.execute(delete(Material).where(Material.referenced == 0, Material.created_at < utcnow()-timedelta(hours=24)))
            s.execute(delete(MaterialJob).where(MaterialJob.created_at < utcnow()-timedelta(hours=24)))
