"""Opt-in real AI + authenticated MySQL acceptance in the dedicated test DB.

WeChat identity is an in-process test adapter. Real WeChat login is validated
separately in the developer tool. This script never clears an entire database.
"""
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.main import create_app
from app.accounts.database import Database, Attempt


async def run():
    settings = Settings(database_testing=True)
    if not settings.deepseek_api_key.get_secret_value():
        print('Real AI acceptance requires the existing local AI configuration.')
        return 2
    database = Database(settings)
    database.migrate()
    identity = {'openid': 'acceptance-' + str(uuid4()), 'unionid': None}
    class AcceptanceWeChat:
        async def exchange(self, code):
            return identity
    app = create_app(settings, wechat=AcceptanceWeChat())
    accounts = app.state.accounts
    uid = None
    result = {'database': settings.mysql_test_database, 'wechat': 'test adapter', 'ai': 'real provider'}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', timeout=180) as client:
            response = await client.post('/api/v1/auth/wechat', json={'code': 'in-process-only', 'agreement_version': '2026-10-12'})
            response.raise_for_status()
            session = response.json()['data']
            uid = session['user']['id']
            client.headers['Authorization'] = 'Bearer ' + session['token']
            response = await client.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'live-quiz'}, json={'text': 'HTTP 为什么是无状态的？', 'question_count': 3, 'difficulty': 'easy'})
            if response.status_code != 200:
                result['error_code'] = response.json()['code']
                return 1
            attempt = response.json()['data']
            result['quiz_generated'] = len(attempt['quiz']['questions']) == 3
            result['answers_hidden'] = all(not q['answers'] for q in attempt['quiz']['questions'])
            with database.session() as transaction:
                trusted = transaction.get(Attempt, attempt['id']).quiz
            for question in trusted['questions']:
                response = await client.post(f"/api/v1/attempts/{attempt['id']}/answers", json={'question_id': question['id'], 'selected': question['answers'], 'elapsed_ms': 1000})
                response.raise_for_status()
            report_body = {'attempt_id': attempt['id']}
            response = await client.post('/api/v1/report/generate', headers={'Idempotency-Key': 'live-report'}, json=report_body)
            if response.status_code == 429 and response.json()['code'] == 'AI_RATE_LIMIT':
                # Internal quiz retries may exhaust the shared rolling-minute cap.
                print('Waiting for the configured rolling-minute AI allowance.', flush=True)
                await asyncio.sleep(61)
                response = await client.post('/api/v1/report/generate', headers={'Idempotency-Key': 'live-report-after-limit'}, json=report_body)
            if response.status_code != 200:
                result['error_code'] = response.json()['code']
                return 1
            report = response.json()['data']
            result['report_generated'] = bool(report['summary'])
            cached = await client.post('/api/v1/report/generate', json=report_body)
            result['report_cached'] = cached.json()['data'] == report
            profile = (await client.get('/api/v1/me')).json()['data']
            result['rewards_correct'] = profile['stats']['xp'] == 30 and profile['stats']['coins'] == 6
            result['cloud_record_saved'] = len((await client.get('/api/v1/learning')).json()['data']['sessions']) == 1
            result['passed'] = all(result.get(k) for k in ('quiz_generated', 'answers_hidden', 'report_generated', 'report_cached', 'rewards_correct', 'cloud_record_saved'))
            return 0 if result['passed'] else 1
    finally:
        if uid:
            accounts.delete_account(uid, identity)
        database.engine.dispose()
        output = Path(__file__).resolve().parents[2] / 'docs/user-system/test-results/live-accounts.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    sys.exit(asyncio.run(run()))
