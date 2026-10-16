"""Transactional preparation lifecycle; shares account identity quotas and locks."""
import json
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, delete

from ..accounts.database import TopicPreparation, Operation, User, MaterialJob, Material
from ..accounts.repository import digest, stamp
from ..errors import AppError
from .models import Preparation, ScopeContent, GenerationOperation
from .snapshots import LearningScopeSnapshot
from .selection import topic_selection


class GroundingRepository:
    def __init__(self, accounts):
        self.accounts = accounts
        self.settings = accounts.settings
        self.database = accounts.database

    def now(self):
        return datetime.fromtimestamp(self.accounts.clock(), timezone.utc).replace(tzinfo=None)

    def _owned(self, s, uid, pid):
        row = s.get(TopicPreparation, pid)
        if not row or row.user_id != uid:
            raise AppError('NOT_FOUND', '学习范围准备不存在', 404)
        return row

    def _expire(self, row, op, quota):
        if row.status == 'running' and (not op or op.status != 'running' or
                not op.deadline_at or op.deadline_at <= self.now() or
                quota.busy_id != op.id or quota.busy_until <= self.accounts.clock()):
            row.status, row.stage, row.error_code = 'failed', 'failed', 'OPERATION_EXPIRED'
            if op and op.status == 'running':
                op.status, op.stage, op.error_code = 'failed', 'failed', 'OPERATION_EXPIRED'
                op.retry_after_seconds = 0
            if op and quota.busy_id == op.id:
                quota.busy_id, quota.busy_until = None, 0
        if row.expires_at <= self.now():
            row.status, row.stage = 'expired', 'expired'

    def _data(self, row, op):
        payload = row.content or {}
        result = Preparation(
            id=row.id, version=row.version, input_text=row.input_text,
            status=row.status, stage=row.stage, content=payload.get('scope'),
            grounding=payload.get('grounding'), evidence=payload.get('evidence', []),
            error_code=row.error_code, retry_after_seconds=op.retry_after_seconds if op and row.status == 'running' else 0,
            created_at=stamp(row.created_at), expires_at=stamp(row.expires_at),
        )
        return result.model_dump(mode='json')

    def create(self, uid, key, text):
        if not self.settings.quiz_grounding_enabled:
            raise AppError('GROUNDING_DISABLED', '主题准备暂时关闭，请稍后再试', 503)
        hashed = digest(json.dumps({'text': text}, ensure_ascii=False, sort_keys=True))
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            old = s.scalar(select(TopicPreparation).where(TopicPreparation.user_id == uid, TopicPreparation.key == key))
            if old:
                if old.digest != hashed:
                    raise AppError('IDEMPOTENCY_CONFLICT', '重复操作的主题不同', 409)
                op = s.get(Operation, old.operation_id)
                self._expire(old, op, quota)
                return self._data(old, op), False
            if quota.busy_id and quota.busy_until > self.accounts.clock():
                raise AppError('AI_BUSY', '请等待当前操作完成', 409)
            if quota.topic_prepare_count >= self.settings.topic_prepare_daily_limit:
                raise AppError('TOPIC_PREPARE_DAILY_LIMIT', '今天的主题准备次数已用完', 429)
            # Namespace internal operation keys so preparation and generation keys may match.
            operation_key = 'prepare:' + digest(key)
            if s.scalar(select(Operation).where(Operation.user_id == uid, Operation.key == operation_key)):
                raise AppError('PREPARATION_EXPIRED', '原准备已清理，请使用新的操作标识', 409)
            oid, pid = str(uuid4()), str(uuid4())
            now = self.now()
            op = Operation(id=oid, user_id=uid, key=operation_key, digest=hashed, kind='prepare',
                           stage='planning', deadline_at=now + timedelta(seconds=self.settings.topic_prepare_timeout_seconds), created_at=now)
            s.add(op)
            s.flush()
            row = TopicPreparation(id=pid, user_id=uid, operation_id=oid, key=key, digest=hashed,
                                   input_text=text, version=1, created_at=now,
                                   expires_at=now + timedelta(hours=self.settings.topic_preparation_ttl_hours))
            s.add(row)
            quota.topic_prepare_count += 1
            quota.busy_id, quota.busy_until = oid, self.accounts.clock() + self.settings.topic_prepare_timeout_seconds + 15
            s.flush()
            return self._data(row, op), True

    def get(self, uid, pid):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            row = self._owned(s, uid, pid)
            op = s.get(Operation, row.operation_id)
            self._expire(row, op, quota)
            return self._data(row, op)

    def _active(self, s, uid, pid):
        user = self.accounts._user(s, uid, True)
        quota = self.accounts._quota(s, user.identity)
        row = self._owned(s, uid, pid)
        op = s.get(Operation, row.operation_id)
        if row.status != 'running' or row.expires_at <= self.now():
            raise AppError('OPERATION_CANCELLED', '主题准备已结束或取消', 409)
        if not op or op.deadline_at <= self.now():
            raise AppError('OPERATION_EXPIRED', '主题准备超时，请重新发起', 409)
        self.accounts._active_operation(s, uid, op.id, quota)
        return row, op, quota

    def stage(self, uid, pid, stage):
        with self.database.session() as s:
            row, op, _ = self._active(s, uid, pid)
            row.stage = op.stage = stage
            op.retry_after_seconds = 0

    def model_call(self, uid, pid, stage=None):
        """Return wait seconds without consuming a call; otherwise atomically count."""
        with self.database.session() as s:
            row, op, quota = self._active(s, uid, pid)
            if op.model_calls >= self.settings.prepare_model_call_limit:
                raise AppError('MODEL_BUDGET_EXHAUSTED', '本次准备已达到模型调用上限', 409)
            if len(quota.calls) >= self.settings.ai_minute_limit:
                delay = max(1, math.ceil(min(quota.calls) + 60 - self.accounts.clock()))
                if (op.deadline_at - self.now()).total_seconds() <= delay + self.settings.model_timeout_seconds:
                    raise AppError('AI_RATE_LIMIT', '剩余时间不足以等待模型额度，请稍后重试', 429)
                row.stage = op.stage = 'waiting_rate_limit'
                op.retry_after_seconds = delay
                return delay
            quota.calls = [*quota.calls, self.accounts.clock()]
            op.model_calls += 1
            op.retry_after_seconds = 0
            if stage:
                row.stage = op.stage = stage
            return 0

    def tool_call(self, uid, pid, name, pages):
        with self.database.session() as s:
            _, op, _ = self._active(s, uid, pid)
            if op.tool_calls >= self.settings.retrieval_tool_call_limit or op.page_attempts + pages > self.settings.retrieval_max_page_attempts:
                raise AppError('TOOL_BUDGET_EXHAUSTED', '本次检索已达到工具调用上限', 409)
            op.tool_calls += 1
            op.page_attempts += pages

    def preparation_page_call(self, uid, pid, pages):
        with self.database.session() as s:
            _, op, _ = self._active(s, uid, pid)
            if op.page_attempts + pages > self.settings.retrieval_max_page_attempts:
                raise AppError('PAGE_BUDGET_EXHAUSTED', '提取页面次数达到上限', 409)
            op.page_attempts += pages

    def finish(self, uid, pid, payload=None, error=None):
        with self.database.session() as s:
            if not s.get(User, uid):
                return None
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            row = self._owned(s, uid, pid)
            op = s.get(Operation, row.operation_id)
            self._expire(row, op, quota)
            if row.status != 'running':
                return self._data(row, op)
            if error:
                row.status, row.stage, row.error_code = 'failed', 'failed', error
                op.status, op.stage, op.error_code = 'failed', 'failed', error
            else:
                self._active(s, uid, pid)
                row.content, row.status, row.stage = payload, 'ready', 'ready'
                # Validate the final public contract before committing either row.
                self._data(row, op)
                op.status, op.stage, op.result = 'succeeded', 'ready', {'preparation_id': row.id}
            op.retry_after_seconds = 0
            if quota.busy_id == op.id:
                quota.busy_id, quota.busy_until = None, 0
            return self._data(row, op)

    def cancel(self, uid, pid):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            row = self._owned(s, uid, pid)
            op = s.get(Operation, row.operation_id)
            self._expire(row, op, quota)
            if row.status == 'running':
                row.status = row.stage = 'cancelled'
                op.status, op.stage, op.error_code = 'failed', 'cancelled', 'OPERATION_CANCELLED'
                op.retry_after_seconds = 0
                if quota.busy_id == op.id:
                    quota.busy_id, quota.busy_until = None, 0
            return self._data(row, op)

    def cleanup(self):
        with self.database.session() as s:
            s.execute(delete(TopicPreparation).where(TopicPreparation.expires_at <= self.now()))

    def handoff_material(self, uid, jid, oid, text, scope):
        """Reuse the material quota/operation; never fabricate a readable material."""
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            job = s.get(MaterialJob, jid)
            if not job or job.user_id != uid or job.status != 'running':
                raise AppError('OPERATION_CANCELLED', '网页任务已结束或取消', 409)
            op = self.accounts._active_operation(s, uid, oid, quota)
            if op.kind != 'material' or op.key != 'material-' + jid:
                raise AppError('OPERATION_EXPIRED', '网页任务已失效', 409)
            scope.check_evidence(set())
            now, pid = self.now(), str(uuid4())
            row = TopicPreparation(id=pid, user_id=uid, operation_id=oid, key='material:' + jid,
                digest=digest(text), input_text=text, version=1, status='ready', stage='ready',
                created_at=now, expires_at=now + timedelta(hours=self.settings.topic_preparation_ttl_hours),
                content={'scope': scope.model_dump(mode='json'), 'evidence': [],
                         'grounding': {'status': 'unverified', 'reason_code': 'PAGE_UNREADABLE'},
                         'origin_material_job_id': jid})
            s.add(row)
            s.flush()
            self._data(row, op)
            job.status, job.stage, job.preparation_id = 'succeeded', 'scope_confirmation', pid
            job.message = '网页未读到，已按你提供的主题准备范围；未联网核实'
            op.status, op.stage, op.result = 'succeeded', 'ready', {'preparation_id': pid}
            quota.busy_id, quota.busy_until = None, 0
            return pid

    def operation_data(self, op):
        return GenerationOperation(key=op.key, status=op.status,
            stage=op.stage if op.status == 'running' else op.status,
            retry_after_seconds=op.retry_after_seconds,
            deadline=stamp(op.deadline_at), error_code=op.error_code).model_dump(mode='json')

    def submit_generation(self, uid, key, body):
        payload = body.model_dump()
        if not body.candidate_ids:
            payload.pop('candidate_ids')  # Keep existing recovery keys compatible.
        else:
            payload['candidate_ids'] = sorted(body.candidate_ids)
        hashed = digest(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            old = s.scalar(select(Operation).where(Operation.user_id == uid, Operation.key == key))
            if old:
                if old.kind != 'quiz' or old.digest != hashed:
                    raise AppError('IDEMPOTENCY_CONFLICT', '重复操作的确认范围或设置不同', 409)
                if old.status == 'running' and (quota.busy_id != old.id or quota.busy_until <= self.accounts.clock() or old.deadline_at <= self.now()):
                    old.status, old.stage, old.error_code = 'failed', 'failed', 'OPERATION_EXPIRED'
                    if quota.busy_id == old.id:
                        quota.busy_id, quota.busy_until = None, 0
                return old.id, self.operation_data(old), False, None
            if not self.settings.quiz_grounding_enabled and body.execution == 'background':
                raise AppError('GROUNDING_DISABLED', '新后台出题暂时关闭，请稍后再试', 503)
            if body.preparation_id:
                row = self._owned(s, uid, body.preparation_id)
                if row.expires_at <= self.now():
                    raise AppError('PREPARATION_EXPIRED', '学习范围已过期，请重新准备', 409)
                if row.status != 'ready':
                    raise AppError('SCOPE_CONFIRMATION_REQUIRED', '请先等待并确认学习范围', 409)
                if row.version != body.scope_version:
                    raise AppError('SCOPE_VERSION_MISMATCH', '学习范围版本已变化，请重新确认', 409)
                scope = ScopeContent.model_validate(row.content['scope'])
                try:
                    if body.candidate_ids:
                        snapshot, points = topic_selection(scope, body.candidate_ids, input_text=row.input_text,
                            preparation_id=row.id, version=row.version)
                    else:
                        candidate, focus, points = scope.selected(body.candidate_id, body.focus_id, body.scope_point_ids)
                        snapshot = LearningScopeSnapshot(input_text=row.input_text, topic=candidate.topic, domain=candidate.domain,
                            focus=focus.name, points=[p.name for p in points], preparation_id=row.id,
                            scope_version=row.version, candidate_id=candidate.id, focus_id=focus.id,
                            scope_point_ids=[p.id for p in points])
                except ValueError:
                    raise AppError('INVALID_SCOPE_SELECTION', '所选方向或知识点不属于该范围', 422) from None
                ids = {sid for p in points for sid in p.evidence_ids}
                context = {'scope': snapshot.model_dump(mode='json'),
                    'segments': [v for v in row.content.get('evidence', []) if v['id'] in ids],
                    'point_evidence': {p.id: p.evidence_ids for p in points},
                    'grounding': row.content.get('grounding'), 'material': None}
            else:
                material = s.get(Material, body.material_id)
                if not material or material.user_id != uid:
                    raise AppError('NOT_FOUND', '材料不存在', 404)
                data = {'id': material.id, **material.content}
                ids = set(body.point_ids or [v['id'] for v in data['segments']])
                if not ids <= {v['id'] for v in data['segments']}:
                    raise AppError('INVALID_RANGE', '所选知识点不属于这份材料', 422)
                selected = [v for v in data['segments'] if v['id'] in ids]
                names = [p['name'] for p in data['points'] if ids.intersection(p['segment_ids'])]
                instruction = data.get('learning_instruction')
                snapshot = LearningScopeSnapshot(input_text=instruction or data['learning_title'],
                    topic=data['learning_title'], domain='用户提供的材料',
                    focus=instruction or '所选材料知识点', points=names[:12])
                context = {'scope': snapshot.model_dump(mode='json'), 'segments': selected, 'material': data,
                           'grounding': {'status': 'material_only'}, 'point_evidence': None}
                material.referenced = 1
            if quota.busy_id and quota.busy_until > self.accounts.clock():
                raise AppError('AI_BUSY', '请等待当前操作完成', 409)
            if quota.quiz_count >= self.settings.quiz_daily_limit:
                raise AppError('DAILY_QUOTA_EXCEEDED', '今天的出题额度已用完', 429)
            oid = str(uuid4())
            duration = 90 if body.execution == 'sync' else self.settings.grounded_generation_timeout_seconds
            op = Operation(id=oid, user_id=uid, key=key, digest=hashed, kind='quiz', stage='retrieving',
                           created_at=self.now(), deadline_at=self.now() + timedelta(seconds=duration))
            s.add(op)
            quota.busy_id, quota.busy_until = oid, self.accounts.clock() + duration + 15
            s.flush()
            return oid, self.operation_data(op), True, context

    def generation_stage(self, uid, oid, stage):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            op = self.accounts._active_operation(s, uid, oid, quota)
            op.stage, op.retry_after_seconds = stage, 0

    def generation_model_call(self, uid, oid, allow_wait=True, stage=None):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            op = self.accounts._active_operation(s, uid, oid, quota)
            if op.model_calls >= self.settings.generation_model_call_limit:
                raise AppError('MODEL_BUDGET_EXHAUSTED', '本次出题已达到模型调用上限', 409)
            if len(quota.calls) >= self.settings.ai_minute_limit:
                if not allow_wait:
                    raise AppError('AI_RATE_LIMIT', 'AI 请求较频繁，请稍后重试', 429)
                wait = max(1, math.ceil(min(quota.calls) + 60 - self.accounts.clock()))
                if (op.deadline_at - self.now()).total_seconds() <= wait + self.settings.model_timeout_seconds:
                    raise AppError('AI_RATE_LIMIT', '剩余时间不足以等待模型额度', 429)
                op.stage, op.retry_after_seconds = 'waiting_rate_limit', wait
                return wait
            if not op.charged:
                if quota.quiz_count >= self.settings.quiz_daily_limit:
                    raise AppError('DAILY_QUOTA_EXCEEDED', '今天的出题额度已用完', 429)
                quota.quiz_count += 1
                op.charged = 1
            quota.calls = [*quota.calls, self.accounts.clock()]
            op.model_calls += 1
            op.retry_after_seconds = 0
            if stage:
                op.stage = stage
            return 0

    def remaining_seconds(self, uid, oid):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            op = self.accounts._active_operation(s, uid, oid, quota)
            return max(0, (op.deadline_at - self.now()).total_seconds())

    def preparation_remaining_seconds(self, uid, pid):
        with self.database.session() as s:
            _, op, _ = self._active(s, uid, pid)
            return max(0, (op.deadline_at - self.now()).total_seconds())

    def generation_tool_call(self, uid, oid, name, pages):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            op = self.accounts._active_operation(s, uid, oid, quota)
            if op.tool_calls >= self.settings.retrieval_tool_call_limit or op.page_attempts + pages > self.settings.retrieval_max_page_attempts:
                raise AppError('TOOL_BUDGET_EXHAUSTED', '本次检索已达到工具调用上限', 409)
            op.tool_calls += 1
            op.page_attempts += pages

    def record_retrieval(self, uid, oid, outcome):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            op = self.accounts._active_operation(s, uid, oid, quota)
            op.retrieval_log = {'tools': outcome.trace, 'model_usage': outcome.usage,
                                'reason_code': outcome.reason_code}

    def operation_page_call(self, uid, oid, pages):
        with self.database.session() as s:
            user = self.accounts._user(s, uid, True)
            quota = self.accounts._quota(s, user.identity)
            op = self.accounts._active_operation(s, uid, oid, quota)
            if op.page_attempts + pages > self.settings.retrieval_max_page_attempts:
                raise AppError('PAGE_BUDGET_EXHAUSTED', '提取页面次数达到上限', 409)
            op.page_attempts += pages
