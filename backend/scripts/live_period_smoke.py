"""Opt-in provider smoke test using only hard-coded synthetic learning data.

Run from backend: python -m scripts.live_period_smoke
No database, account, material, or user record is read or changed.
"""
import asyncio
import json
from pathlib import Path
from time import monotonic

from app.config import Settings
from app.llm import ModelGateway
from app.materials.services import period_narrative


async def main():
    titles = ['FastAPI', 'LangGraph', 'Python', 'HTTP', 'SQL', '单片机', '古诗阅读', '戏剧赏析', '音乐鉴赏', '团队沟通', '地理基础']
    concepts = ['基础概念', '实际应用', '常见误区', '场景比较', '材料理解']
    topics = [{'id': f'topic-{i}', 'name': title, 'points': [
        {'id': f'{i * 5 + j:020x}', 'name': title + '的' + name, 'total': 3, 'correct': j % 4,
         'accuracy': round(j % 4 / 3 * 100), 'status': 'weak' if j % 4 < 3 else 'mastered'}
        for j, name in enumerate(concepts[:1 if i == 10 else 5])]} for i, title in enumerate(titles)]
    totals = {'total': 153, 'correct': 72, 'accuracy': 47, 'rounds': 11, 'topics': 11, 'duration_ms': 600000, 'learning_days': 5}
    snapshot = {'sections': ['overview', 'performance', 'advice'],
        'current': {'totals': totals, 'trend': [], 'types': []},
        'previous': {'totals': {**totals, 'total': 0, 'correct': 0, 'accuracy': None}, 'trend': [], 'types': []},
        'knowledge': {'topics': topics}, 'provenance': [
            {'title': title, 'verification': {'status': 'unknown', 'counts': {'unknown': 3}}} for title in titles]}
    settings = Settings()
    runs = []
    for sections in [['overview', 'performance', 'advice'], ['advice'], ['overview', 'performance']]:
        snapshot['sections'] = sections
        gateway = ModelGateway(settings, operation_id='synthetic-period-smoke')
        start = monotonic()
        content = await period_narrative(snapshot, gateway)
        ids = {point['id'] for topic in topics for point in topic['points']}
        assert all(item['point_id'] in ids for item in content['findings'] + content['suggestions'])
        if 'advice' not in sections: assert not content['findings'] and not content['suggestions']
        runs.append({'sections': sections, 'seconds': round(monotonic() - start, 2),
                     'model_attempts': gateway.last_attempts, 'summary_count': len(content['summary']),
                     'findings_count': len(content['findings']), 'suggestions_count': len(content['suggestions']), 'status': 'passed'})
        print(json.dumps(runs[-1], ensure_ascii=False), flush=True)
    receipt = {'data_kind': 'hard-coded synthetic data only; no database access', 'topics': len(topics),
               'points': sum(len(t['points']) for t in topics), 'runs': runs}
    Path('test-results/period-synthetic-smoke.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__': asyncio.run(main())
