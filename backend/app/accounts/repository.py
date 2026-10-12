import csv
import hashlib
import hmac
import io
import json
import logging
import secrets
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select, delete, func
from sqlalchemy.dialects.mysql import insert
from .database import User, LoginSession, QuizRow, Attempt, Reward, WrongRow, Quota, Operation, utcnow
from ..errors import AppError
from ..rewards import question_reward, new_quiz_reward

SHANGHAI = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)

def stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def correct(question, selected):
    return set(question['answers']) == set(selected)

def attempt_stats(a):
    points = {}
    answers = {v['question_id']: v for v in a.answers}
    results = []
    for q in a.quiz['questions']:
        ok = q['id'] in answers and correct(q, answers[q['id']]['selected'])
        results.append({'question_id': q['id'], 'is_correct': ok})
        point = points.setdefault(q['knowledge_point'], {'name': q['knowledge_point'], 'total': 0, 'correct': 0, 'accuracy': 0})
        point['total'] += 1
        point['correct'] += int(ok)
        point['accuracy'] = int(point['correct'] / point['total'] * 100 + .5)
    count = sum(v['is_correct'] for v in results)
    total = len(results)
    reward = question_reward(a.quiz)
    return {'total': total, 'correct_count': count, 'accuracy': int(count / total * 100 + .5), 'duration_ms': sum(v['elapsed_ms'] for v in a.answers), 'xp': count * reward['xp'] if a.mode == 'new' else 0, 'coins': count * reward['coins'] if a.mode == 'new' else 0, 'knowledge_points': list(points.values()), 'results': results}

def serialize(a):
    quiz = deepcopy(a.quiz)
    answered = {v['question_id'] for v in a.answers}
    for q in quiz['questions']:
        if q['id'] not in answered:
            q['answers'], q['explanation'] = [], ''
    return {'id': a.id, 'quiz': quiz, 'mode': a.mode, 'answers': a.answers, 'cursor': a.cursor, 'pending_ms': 0, 'started_at': stamp(a.started_at), 'completed_at': stamp(a.completed_at), 'report': a.report, 'review_keys': a.review_keys}


class Accounts:
    def __init__(self, settings, database, clock=time.time):
        self.settings, self.database, self.clock = settings, database, clock

    def fingerprint(self, value):
        secret = self.settings.identity_hash_secret.get_secret_value()
        if len(secret) < 32:
            raise AppError('IDENTITY_SECRET_REQUIRED', '请配置至少 32 字符的身份摘要密钥', 503)
        return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()

    def _quota(self, s, identity):
        day = datetime.fromtimestamp(self.clock(), SHANGHAI).date().isoformat()
        s.execute(insert(Quota).values(identity=identity, day=day, quiz_count=0, calls=[], busy_until=0).on_duplicate_key_update(identity=identity))
        q = s.scalar(select(Quota).where(Quota.identity == identity).with_for_update())
        if q.day != day:
            q.day, q.quiz_count = day, 0
        q.calls = [v for v in q.calls if v > self.clock() - 60]
        return q

    def _user(self, s, uid, lock=False):
        u = s.get(User, uid)
        if u is None:
            raise AppError('AUTH_REQUIRED', '请重新微信登录', 401)
        if lock:
            self._quota(s, u.identity)
            u = s.scalar(select(User).where(User.id == uid).with_for_update().execution_options(populate_existing=True))
            if u is None:
                raise AppError('AUTH_REQUIRED', '请重新微信登录', 401)
        return u

    def _attempt(self, s, uid, aid):
        a = s.scalar(select(Attempt).where(Attempt.id == aid, Attempt.user_id == uid))
        if a is None:
            raise AppError('NOT_FOUND', '学习记录不存在', 404)
        return a

    def login_rate(self, ip):
        with self.database.session() as s:
            q = self._quota(s, self.fingerprint('login:' + ip))
            if len(q.calls) >= self.settings.login_minute_limit:
                raise AppError('LOGIN_RATE_LIMIT', '登录过于频繁，请稍后重试', 429)
            q.calls = [*q.calls, self.clock()]
            q.retire_after = self.clock() + 61

    def login(self, identity, agreement):
        key = self.fingerprint(self.settings.wechat_app_id + ':' + identity['openid'])
        token = secrets.token_urlsafe(48)
        with self.database.session() as s:
            q = self._quota(s, key)
            q.retire_after = None
            u = s.scalar(select(User).where(User.identity == key).with_for_update())
            if not u:
                u = User(id=str(uuid4()), identity=key, appid=self.settings.wechat_app_id, openid=identity['openid'], unionid=identity.get('unionid'), agreement_version=agreement)
                s.add(u)
                s.flush()
            else:
                if identity.get('unionid'): u.unionid = identity['unionid']
                u.agreement_version, u.consent_at = agreement, utcnow()
            s.add(LoginSession(digest=digest(token), user_id=u.id, expires_at=utcnow() + timedelta(days=self.settings.session_days)))
            return {'token': token, 'expires_at': stamp(utcnow() + timedelta(days=self.settings.session_days)), 'user': self._profile(s, u)}

    def authenticate(self, token):
        with self.database.session() as s:
            session = s.get(LoginSession, digest(token))
            if not session or session.expires_at <= utcnow() or not s.get(User, session.user_id):
                raise AppError('AUTH_REQUIRED', '登录已过期，请重新微信登录', 401)
            return session.user_id

    def logout(self, token):
        with self.database.session() as s:
            s.execute(delete(LoginSession).where(LoginSession.digest == digest(token)))

    def _profile(self, s, u):
        completed = list(s.scalars(select(Attempt).where(Attempt.user_id == u.id, Attempt.mode == 'new', Attempt.completed_at.is_not(None))))
        counts = [attempt_stats(a) for a in completed]
        days = {a.completed_at.replace(tzinfo=timezone.utc).astimezone(SHANGHAI).date() for a in completed}
        day = datetime.fromtimestamp(self.clock(), SHANGHAI).date()
        if day not in days: day -= timedelta(days=1)
        streak = 0
        while day in days:
            streak += 1
            day -= timedelta(days=1)
        q = self._quota(s, u.identity)
        total = sum(v['total'] for v in counts)
        return {'id': u.id, 'nickname': u.nickname, 'avatar_version': u.avatar_version, 'stats': {'xp': u.xp, 'coins': u.coins, 'level': u.xp // 100 + 1, 'topics': len(completed), 'streak': streak, 'accuracy': int(sum(v['correct_count'] for v in counts) / total * 100 + .5) if total else 0}, 'quota': {'remaining': max(0, self.settings.quiz_daily_limit - q.quiz_count), 'daily_limit': self.settings.quiz_daily_limit}}

    def me(self, uid):
        with self.database.session() as s:
            return self._profile(s, self._user(s, uid, True))

    def nickname(self, uid, nickname):
        with self.database.session() as s:
            u = self._user(s, uid, True)
            u.nickname = nickname
            return self._profile(s, u)

    def avatar(self, uid, data=None):
        encoded = None
        if data is not None:
            if len(data) > 2 * 1024 * 1024:
                raise AppError('AVATAR_TOO_LARGE', '头像不能超过 2MB', 422)
            try:
                with Image.open(io.BytesIO(data)) as source:
                    if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 16000000:
                        raise ValueError()
                    image = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'), (256, 256))
                    buffer = io.BytesIO()
                    image.save(buffer, 'JPEG', quality=85)
                    encoded = buffer.getvalue()
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                raise AppError('INVALID_AVATAR', '请选择有效的 PNG、JPEG 或 WebP 头像', 422) from None
        with self.database.session() as s:
            u = self._user(s, uid, True)
            if encoded is not None:
                u.avatar, u.avatar_version = encoded, u.avatar_version + 1
                return self._profile(s, u)
            if not u.avatar:
                raise AppError('NOT_FOUND', '尚未设置头像', 404)
            return u.avatar

    def store_quiz(self, uid, quiz, operation_id=None):
        quiz = {**deepcopy(quiz), 'reward': new_quiz_reward(quiz['difficulty'])}
        with self.database.session() as s:
            u = self._user(s, uid, True)
            q = self._quota(s, u.identity)
            op = self._active_operation(s, uid, operation_id, q) if operation_id else None
            s.add(QuizRow(id=quiz['id'], user_id=uid, content=quiz))
            s.flush()
            a = Attempt(id=str(uuid4()), user_id=uid, quiz_id=quiz['id'], quiz=quiz, mode='new')
            s.add(a)
            s.flush()
            result = serialize(a)
            if op:
                op.status, op.result = 'succeeded', result
                q.busy_id, q.busy_until = None, 0
        if op: logger.info('ai_finished operation=%s status=succeeded', operation_id)
        return result

    def replay(self, uid, quiz_id):
        with self.database.session() as s:
            self._user(s, uid, True)
            q = s.scalar(select(QuizRow).where(QuizRow.id == quiz_id, QuizRow.user_id == uid))
            if not q: raise AppError('NOT_FOUND', '关卡不存在', 404)
            first = s.scalar(select(Attempt).where(Attempt.user_id == uid, Attempt.quiz_id == quiz_id, Attempt.mode == 'new'))
            if first and not first.completed_at: return serialize(first)
            a = Attempt(id=str(uuid4()), user_id=uid, quiz_id=quiz_id, quiz=q.content, mode='replay')
            s.add(a)
            s.flush()
            return serialize(a)

    def review(self, uid, keys):
        with self.database.session() as s:
            self._user(s, uid, True)
            questions = []
            for key in keys:
                w = s.get(WrongRow, (uid, key))
                if not w: raise AppError('NOT_FOUND', '错题不存在', 404)
                a = self._attempt(s, uid, w.attempt_id)
                question = deepcopy(next(q for q in a.quiz['questions'] if q['id'] == w.question_id))
                # Question IDs may repeat across quizzes; review keeps unique IDs.
                question['id'] = f'review-{len(questions)}'
                questions.append(question)
            quiz = {'id': str(uuid4()), 'created_at': stamp(utcnow()), 'source_text': '云端错题重温', 'title': '旧识重温', 'summary': '把模糊的知识擦清楚', 'difficulty': 'easy', 'questions': questions}
            a = Attempt(id=str(uuid4()), user_id=uid, quiz=quiz, mode='review', review_keys=keys)
            s.add(a)
            s.flush()
            return serialize(a)

    def attempt(self, uid, aid):
        with self.database.session() as s:
            self._user(s, uid)
            return serialize(self._attempt(s, uid, aid))

    def answer(self, uid, aid, answer):
        with self.database.session() as s:
            u = self._user(s, uid, True)
            a = self._attempt(s, uid, aid)
            old = next((v for v in a.answers if v['question_id'] == answer['question_id']), None)
            if old:
                if set(old['selected']) != set(answer['selected']):
                    raise AppError('ANSWER_LOCKED', '首次答案已锁定', 409)
                return {'session': serialize(a), 'user': self._profile(s, u)}
            if a.completed_at: raise AppError('ANSWER_LOCKED', '本轮学习已完成', 409)
            index = next((i for i, q in enumerate(a.quiz['questions']) if q['id'] == answer['question_id']), None)
            if index is None: raise AppError('INVALID_INPUT', '题目不存在', 422)
            q = a.quiz['questions'][index]
            selected = answer['selected']
            if q['id'] != answer['question_id'] or not selected or len(set(selected)) != len(selected) or any(v not in [o['id'] for o in q['options']] for v in selected) or (q['type'] != 'multi' and len(selected) != 1):
                raise AppError('INVALID_INPUT', '请提交有效答案', 422)
            ok = correct(q, selected)
            a.answers = [*a.answers, answer]
            a.cursor = index
            if a.mode == 'new':
                if ok:
                    reward = s.scalar(select(Reward).where(Reward.user_id == uid, Reward.quiz_id == a.quiz_id, Reward.question_id == q['id']))
                    if reward is None:
                        rate = question_reward(a.quiz)
                        s.add(Reward(id=str(uuid4()), user_id=uid, quiz_id=a.quiz_id, question_id=q['id'], xp=rate['xp'], coins=rate['coins']))
                        u.xp += rate['xp']
                        u.coins += rate['coins']
                else:
                    s.add(WrongRow(user_id=uid, key=f'{a.id}:{q["id"]}', attempt_id=a.id, question_id=q['id']))
            elif a.mode == 'review':
                w = s.get(WrongRow, (uid, a.review_keys[index]))
                if w:
                    w.mastered = int(ok)
                    w.reviews = [*w.reviews, {'at': stamp(utcnow()), 'correct': ok}]
            if len(a.answers) == len(a.quiz['questions']):
                a.completed_at = utcnow()
            s.flush()
            return {'session': serialize(a), 'user': self._profile(s, u)}

    def progress(self, uid, aid, cursor):
        with self.database.session() as s:
            self._user(s, uid, True)
            a = self._attempt(s, uid, aid)
            if not 0 <= cursor < len(a.quiz['questions']):
                raise AppError('INVALID_INPUT', '题号超出本轮范围', 422)
            a.cursor = cursor
            return serialize(a)

    def learning(self, uid):
        with self.database.session() as s:
            self._user(s, uid)
            sessions = list(s.scalars(select(Attempt).where(Attempt.user_id == uid).order_by(Attempt.started_at, Attempt.id)))
            wrongs = {w.key: {'mastered': bool(w.mastered), 'reviews': w.reviews} for w in s.scalars(select(WrongRow).where(WrongRow.user_id == uid))}
            return {'version': 1, 'sessions': [serialize(a) for a in sessions], 'wrongs': wrongs, 'welcome': True, 'activeId': next((a.id for a in reversed(sessions) if not a.completed_at), None), 'draft': {'text': '', 'count': 5, 'difficulty': 'easy'}}

    def history(self, uid, page=1, page_size=20, status='all', mode='all', days='all'):
        with self.database.session() as s:
            self._user(s, uid)
            filters = [Attempt.user_id == uid]
            if status == 'completed': filters.append(Attempt.completed_at.is_not(None))
            if status == 'unfinished': filters.append(Attempt.completed_at.is_(None))
            if mode != 'all': filters.append(Attempt.mode == mode)
            if days != 'all':
                today = datetime.fromtimestamp(self.clock(), SHANGHAI).date()
                start = datetime.combine(today - timedelta(days=int(days) - 1), datetime.min.time(), SHANGHAI).astimezone(timezone.utc).replace(tzinfo=None)
                filters.append(Attempt.started_at >= start)
            total = s.scalar(select(func.count()).select_from(Attempt).where(*filters))
            rows = s.scalars(select(Attempt).where(*filters).order_by(Attempt.started_at.desc(), Attempt.id.desc()).offset((page - 1) * page_size).limit(page_size))
            return {'items': [serialize(a) for a in rows], 'total': total, 'page': page, 'page_size': page_size}

    def wrong(self, uid, key=None, mastered=True):
        with self.database.session() as s:
            self._user(s, uid, True)
            rows = list(s.scalars(select(WrongRow).where(WrongRow.user_id == uid))) if key is None else [s.get(WrongRow, (uid, key))]
            for w in rows:
                if not w: raise AppError('NOT_FOUND', '错题不存在', 404)
                w.mastered = int(mastered)

    def reserve(self, uid, key, kind, payload, aid=None):
        hashed = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        with self.database.session() as s:
            u = self._user(s, uid, True)
            q = self._quota(s, u.identity)
            old = s.scalar(select(Operation).where(Operation.user_id == uid, Operation.key == key))
            if old:
                if old.digest != hashed or old.kind != kind: raise AppError('IDEMPOTENCY_CONFLICT', '重复操作的参数不同', 409)
                if old.status == 'succeeded': return old.id, old.result
                if old.status == 'failed': raise AppError(old.error_code or 'OPERATION_FAILED', '该操作已失败，请重新发起', 409)
                if q.busy_id != old.id or q.busy_until <= self.clock():
                    raise AppError('OPERATION_EXPIRED', '生成已过期，请重新发起', 409)
                raise AppError('AI_BUSY', '该操作仍在处理，请稍后查询', 409)
            if kind == 'report':
                a = self._attempt(s, uid, aid)
                if a.report: return '', a.report
                if not a.completed_at or a.mode == 'review': raise AppError('ATTEMPT_INCOMPLETE', '请先完成本轮学习', 409)
                if a.report_attempts >= self.settings.report_attempt_limit: raise AppError('REPORT_RETRY_LIMIT', '本份报告已达到生成次数上限', 429)
            if q.busy_id and q.busy_until > self.clock(): raise AppError('AI_BUSY', '请等待当前生成完成', 409)
            if q.busy_id:
                expired = s.get(Operation, q.busy_id)
                if expired: expired.status, expired.error_code = 'failed', 'OPERATION_EXPIRED'
            if kind == 'quiz' and q.quiz_count >= self.settings.quiz_daily_limit: raise AppError('DAILY_QUOTA_EXCEEDED', '今天的出题额度已用完，明天再来吧', 429)
            if len(q.calls) >= self.settings.ai_minute_limit: raise AppError('AI_RATE_LIMIT', 'AI 请求较频繁，请稍后重试', 429)
            oid = str(uuid4())
            s.add(Operation(id=oid, user_id=uid, key=key, digest=hashed, kind=kind, attempt_id=aid))
            # Covers all bounded model attempts and their backoff, not only one call.
            q.busy_id, q.busy_until = oid, self.clock() + self.settings.model_timeout_seconds * self.settings.model_max_attempts + 30
            return oid, None

    def _active_operation(self, s, uid, oid, q):
        op = s.get(Operation, oid)
        if not op or op.user_id != uid or op.status != 'running' or q.busy_id != oid or q.busy_until <= self.clock():
            raise AppError('OPERATION_EXPIRED', '生成已过期，请重新发起', 409)
        return op

    def model_call(self, uid, oid):
        with self.database.session() as s:
            u = self._user(s, uid, True)
            q = self._quota(s, u.identity)
            op = self._active_operation(s, uid, oid, q)
            if len(q.calls) >= self.settings.ai_minute_limit: raise AppError('AI_RATE_LIMIT', 'AI 请求较频繁，请稍后重试', 429)
            if not op.charged:
                if op.kind == 'quiz':
                    if q.quiz_count >= self.settings.quiz_daily_limit: raise AppError('DAILY_QUOTA_EXCEEDED', '今天的出题额度已用完', 429)
                    q.quiz_count += 1
                else:
                    a = self._attempt(s, uid, op.attempt_id)
                    a.report_attempts += 1
                op.charged = 1
            q.calls = [*q.calls, self.clock()]
        logger.info('ai_call operation=%s kind=%s minute_calls=%s', oid, op.kind, len(q.calls))

    def finish(self, uid, oid, result=None, error=None):
        with self.database.session() as s:
            u = s.get(User, uid)
            if not u: return
            self._user(s, uid, True)
            q = self._quota(s, u.identity)
            op = s.get(Operation, oid)
            if op and op.user_id == uid and op.status == 'running':
                if not error:
                    self._active_operation(s, uid, oid, q)
                op.status, op.result, op.error_code = ('failed', None, error) if error else ('succeeded', result, None)
                if not error and op.kind == 'report':
                    self._attempt(s, uid, op.attempt_id).report = result
            if q.busy_id == oid: q.busy_id, q.busy_until = None, 0
        logger.info('ai_finished operation=%s status=%s error_code=%s', oid, 'failed' if error else 'succeeded', error)

    def report_input(self, uid, aid):
        with self.database.session() as s:
            self._user(s, uid)
            a = self._attempt(s, uid, aid)
            return {'quiz': a.quiz, 'answers': a.answers, 'mode': a.mode}

    def operation(self, uid, key):
        with self.database.session() as s:
            self._user(s, uid)
            op = s.scalar(select(Operation).where(Operation.user_id == uid, Operation.key == key))
            if not op: raise AppError('NOT_FOUND', '操作不存在', 404)
            return {'status': op.status, 'result': op.result, 'error_code': op.error_code}

    def export(self, uid):
        data = self.learning(uid)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['主题', '模式', '开始时间', '完成时间', '正确率', 'XP', '金币'])
        for a in data['sessions']:
            # Avoid spreadsheet formula execution from user/AI generated titles.
            title = a['quiz']['title']
            if title.lstrip().startswith(('=', '+', '-', '@')): title = "'" + title
            from types import SimpleNamespace
            stats = attempt_stats(SimpleNamespace(quiz=a['quiz'], answers=a['answers'], mode=a['mode']))
            writer.writerow([title, a['mode'], a['started_at'], a['completed_at'], stats['accuracy'], stats['xp'], stats['coins']])
        return '\ufeff' + output.getvalue()

    def delete_account(self, uid, identity):
        with self.database.session() as s:
            u = self._user(s, uid, True)
            if u.openid != identity['openid']: raise AppError('IDENTITY_MISMATCH', '请使用当前账号的微信验证', 403)
            q = self._quota(s, u.identity)
            now = datetime.fromtimestamp(self.clock(), SHANGHAI)
            tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), SHANGHAI).timestamp()
            q.retire_after = max(tomorrow, q.busy_until, self.clock() + 60)
            s.delete(u)

    def cleanup(self):
        with self.database.session() as s:
            s.execute(delete(Quota).where(Quota.retire_after.is_not(None), Quota.retire_after < self.clock()))
            s.execute(delete(LoginSession).where(LoginSession.expires_at < utcnow()))
