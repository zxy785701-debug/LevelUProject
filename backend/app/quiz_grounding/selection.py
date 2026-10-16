"""Resolve confirmed topic cards to a balanced, server-owned learning scope."""
from collections import deque
from hashlib import sha256
import json

from .snapshots import LearningScopeSnapshot, SelectedTopic


def topic_selection(scope, candidate_ids, *, input_text, preparation_id, version):
    candidates = [c for c in scope.candidates if c.id in candidate_ids]
    if not candidate_ids or len(candidates) != len(candidate_ids):
        raise ValueError('所选主题不属于当前范围')
    queues = []
    for candidate in candidates:
        focuses = [deque((focus, p) for p in focus.points) for focus in candidate.focuses]
        points = deque()
        while any(focuses):
            for focus in focuses:
                if focus:
                    points.append(focus.popleft())
        queues.append(points)
    picked = [[] for _ in candidates]
    # Keep the existing 12-point prompt budget, balanced across all selected topics.
    while sum(map(len, picked)) < 12 and any(queues):
        for index, queue in enumerate(queues):
            if queue and sum(map(len, picked)) < 12:
                focus, point = queue.popleft()
                identity = json.dumps([candidates[index].id, focus.id, point.id], ensure_ascii=False)
                point_id = 'point-' + sha256(identity.encode()).hexdigest()[:32]
                picked[index].append(point.model_copy(update={'id': point_id}))
    points = [p for group in picked for p in group]
    topics = [SelectedTopic(candidate_id=c.id, topic=c.topic, domain=c.domain,
                            scope_point_ids=[p.id for p in group]) for c, group in zip(candidates, picked)]
    snapshot = LearningScopeSnapshot(input_text=input_text,
        topic=' / '.join(dict.fromkeys(c.topic for c in candidates))[:180],
        domain=' / '.join(c.domain for c in candidates)[:180], focus='综合学习所选主题，兼顾每个主题',
        points=[p.name for p in points], preparation_id=preparation_id, scope_version=version,
        scope_point_ids=[p.id for p in points], selected_topics=topics)
    return snapshot, points
