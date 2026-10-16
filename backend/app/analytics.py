"""Statistics are computed from trusted server answers, never model estimates."""
import hashlib
import unicodedata
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from .accounts.database import Attempt, WrongRow
from .accounts.repository import SHANGHAI, correct, stamp
from .errors import AppError
from .quiz_grounding.reporting import verification


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', text).strip().lower().split())


def identifier(topic, point):
    return hashlib.sha256((normalized(topic) + '\n' + normalized(point)).encode()).hexdigest()[:20]


def date_range(days, start=None, end=None, today=None):
    today = today or datetime.now(SHANGHAI).date()
    try:
        if days == 'custom':
            first, last = date.fromisoformat(start), date.fromisoformat(end)
            if first > last or last > today or (last-first).days >= 366: raise ValueError()
        elif days in ('7', '30'): first, last = today-timedelta(days=int(days)-1), today
        elif days == 'all': first, last = None, today
        else: raise ValueError()
        return first, last
    except (ValueError, TypeError): raise AppError('INVALID_RANGE', '请选择有效日期范围，最长 366 天且不能晚于今天', 422) from None


def bounds(first, last):
    convert = lambda d: datetime.combine(d, datetime.min.time(), SHANGHAI).astimezone(timezone.utc).replace(tzinfo=None)
    return convert(first) if first else None, convert(last+timedelta(days=1))


def mastery_rows(session, uid, attempts, before=None):
    wrongs = {w.key: w for w in session.scalars(select(WrongRow).where(WrongRow.user_id == uid))}
    topics = {}
    seen = set()
    for a in attempts:
        if a.quiz_id in seen: continue
        seen.add(a.quiz_id)
        title = a.quiz['title']
        topic = topics.setdefault(normalized(title), {'id': identifier(title, ''), 'name': title, 'points': {}})
        answers = {v['question_id']: v for v in a.answers}
        for q in a.quiz['questions']:
            if q['id'] not in answers: continue
            pid = identifier(title, q['knowledge_point'])
            point = topic['points'].setdefault(pid, {'id': pid, 'name': q['knowledge_point'], 'total': 0, 'correct': 0, 'attempt_ids': [], 'wrong_keys': [], 'latest_at': stamp(a.completed_at)})
            ok = correct(q, answers[q['id']]['selected'])
            key = f'{a.id}:{q["id"]}'
            w = wrongs.get(key)
            reviews = [v for v in w.reviews if before is None or datetime.fromisoformat(v['at']).astimezone(timezone.utc).replace(tzinfo=None) < before] if w else []
            if reviews:
                last = max(reviews, key=lambda v: v['at'])
                ok = last['correct']
                point['latest_at'] = max(point['latest_at'], last['at'])
            point['total'] += 1; point['correct'] += int(ok)
            if a.id not in point['attempt_ids']: point['attempt_ids'].append(a.id)
            if not ok: point['wrong_keys'].append(key)
    result = []
    for topic in topics.values():
        values = list(topic['points'].values())
        for point in values:
            point['accuracy'] = int(point['correct']/point['total']*100+.5)
            point['status'] = 'weak' if point['wrong_keys'] else 'mastered' if point['total'] >= 3 and point['accuracy'] >= 80 else 'explore'
        topic['points'] = sorted(values, key=lambda v: (v['status'] != 'weak', -v['total'], v['name']))
        result.append(topic)
    return {'topics': sorted(result, key=lambda v: v['name']), 'rule': '至少 3 道不同题且正确率达到 80%；未巩固错误优先显示待巩固。掌握度是答题样本估计。'}


def analytics_rows(attempts, first, last):
    daily, kinds, titles = {}, {}, set()
    total = correct_count = duration = 0
    seen = set()
    included = []
    for a in attempts:
        if a.quiz_id in seen: continue
        seen.add(a.quiz_id)
        day = a.completed_at.replace(tzinfo=timezone.utc).astimezone(SHANGHAI).date()
        if (first and day < first) or day > last: continue
        included.append(a)
        titles.add(normalized(a.quiz['title']))
        bucket = daily.setdefault(day.isoformat(), {'total': 0, 'correct': 0})
        answers = {v['question_id']: v for v in a.answers}
        for q in a.quiz['questions']:
            answer = answers.get(q['id'])
            if not answer: continue
            ok = int(correct(q, answer['selected']))
            total += 1; correct_count += ok; duration += answer['elapsed_ms']
            bucket['total'] += 1; bucket['correct'] += ok
            kind = kinds.setdefault(q['type'], {'type': q['type'], 'total': 0, 'correct': 0})
            kind['total'] += 1; kind['correct'] += ok
    accuracy = lambda n, d: int(n/d*100+.5) if d else None
    for v in kinds.values(): v['accuracy'] = accuracy(v['correct'], v['total'])
    trend = []
    if first:
        day = first
        while day <= last:
            v = daily.get(day.isoformat(), {'total': 0, 'correct': 0})
            trend.append({'date': day.isoformat(), **v, 'accuracy': accuracy(v['correct'], v['total'])})
            day += timedelta(days=1)
    else:
        trend = [{'date': d, **v, 'accuracy': accuracy(v['correct'], v['total'])} for d, v in sorted(daily.items())]
    return {'range': {'start': first.isoformat() if first else None, 'end': last.isoformat()}, 'totals': {'total': total, 'correct': correct_count, 'accuracy': accuracy(correct_count, total), 'duration_ms': duration, 'topics': len(titles), 'rounds': len(included), 'learning_days': len(daily)}, 'trend': trend, 'types': list(kinds.values())}


class Analytics:
    def __init__(self, accounts): self.accounts = accounts

    def _rows(self, s, uid, first=None, last=None):
        query = select(Attempt).where(Attempt.user_id == uid, Attempt.mode == 'new', Attempt.completed_at.is_not(None))
        if last:
            a, b = bounds(first, last)
            query = query.where(Attempt.completed_at < b)
            if a: query = query.where(Attempt.completed_at >= a)
        return list(s.scalars(query.order_by(Attempt.completed_at, Attempt.id)))

    def stats(self, uid, days='7', start=None, end=None):
        today = datetime.fromtimestamp(self.accounts.clock(), SHANGHAI).date()
        first, last = date_range(days, start, end, today)
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid)
            return analytics_rows(self._rows(s, uid, first, last), first, last)

    def map(self, uid):
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid)
            return mastery_rows(s, uid, self._rows(s, uid))

    def snapshot(self, uid, days, start, end, sections):
        today = datetime.fromtimestamp(self.accounts.clock(), SHANGHAI).date()
        first, last = date_range(days, start, end, today)
        length = (last-first).days+1
        previous_first, previous_last = first-timedelta(days=length), first-timedelta(days=1)
        with self.accounts.database.session() as s:
            self.accounts._user(s, uid)
            rows = self._rows(s, uid, previous_first, last)
            current_rows = [a for a in rows if a.completed_at >= bounds(first, last)[0]]
            current = analytics_rows(current_rows, first, last)
            if not current['totals']['total']: raise AppError('NO_LEARNING_DATA', '这个时段还没有完成的学习，先完成一关吧', 409)
            previous = analytics_rows(rows, previous_first, previous_last)
            tree = mastery_rows(s, uid, current_rows, bounds(first, last)[1])
            provenance = [{'attempt_id': a.id, 'quiz_id': a.quiz_id, 'title': a.quiz['title'],
                           'verification': verification(a.quiz), 'source': a.quiz.get('source'),
                           'learning_scope': a.quiz.get('learning_scope')} for a in current_rows]
            # Full trusted evidence affects the cache, including reviews and elapsed time.
            return {'version': 2, 'sections': sorted(sections), 'current': current, 'previous': previous, 'knowledge': tree,
                    'attempt_ids': [a.id for a in current_rows], 'provenance': provenance}
