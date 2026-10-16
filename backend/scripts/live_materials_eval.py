"""Opt-in live verification. Only creates and removes its own temporary account."""
import asyncio
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from app.config import Settings
from app.main import create_app
from app.accounts.database import Database
from app.accounts.repository import Accounts
from app.materials.sources import Sources


async def main(sources_only=False):
    settings = Settings()
    path = Path(__file__).resolve().parents[1]/'test-results/multisource/live-sources.json'
    output = json.loads(path.read_text(encoding='utf-8')) if sources_only and path.exists() else {'web': [], 'video': [], 'model': {}}
    output['web'], output['video'] = [], []
    sources = Sources(settings)
    for url in ('https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Overview', 'https://example.com'):
        try:
            result = await sources.web(url)
            output['web'].append({'url':url,'status':'passed','title':result['title'],'characters':sum(len(s['text']) for s in result['segments'])})
        except Exception as e: output['web'].append({'url':url,'status':'failed','code':getattr(e,'code',type(e).__name__),'message':str(e)[:160]})
    # Public examples from the supported platforms; availability is measured, not assumed.
    for url in ('https://www.youtube.com/watch?v=UF8uR6Z6KLc', 'https://www.bilibili.com/video/BV13x41117TL'):
        try:
            result = await sources.video(url, 0, 60)
            output['video'].append({'url':url,'status':'passed','title':result['title'],'segments':len(result['segments'])})
        except Exception as e: output['video'].append({'url':url,'status':'failed','code':getattr(e,'code',type(e).__name__),'message':str(e)[:160]})
    if sources_only:
        pass  # Preserve the separately recorded model verification without charging again.
    elif not settings.deepseek_api_key.get_secret_value():
        output['model'] = {'status':'unavailable','reason':'MODEL_NOT_CONFIGURED'}
    else:
        db = Database(settings); db.migrate(); accounts = Accounts(settings, db)
        identity = {'openid':'materials-live-'+str(uuid4())}
        account = accounts.login(identity, '2026-10-12'); uid = account['user']['id']
        try:
            app = create_app(settings, accounts=accounts)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization':'Bearer '+account['token']}, timeout=120) as c:
                r = await c.post('/api/v1/materials/document', files={'file':('HTTP.txt','HTTP 每次请求彼此独立。Cookie 存放在客户端并随请求发送。Session 通常在服务端保存会话信息，会话标识可以由 Cookie 携带。'.encode(),'text/plain')})
                r.raise_for_status(); jid = r.json()['data']['id']
                job = (await c.get('/api/v1/material-jobs/'+jid)).json()['data']
                if job['status'] != 'succeeded': raise RuntimeError(job.get('error_code'))
                r = await c.post('/api/v1/quiz/generate', json={'material_id':job['material_id'],'question_count':3,'difficulty':'easy'})
                r.raise_for_status(); attempt = r.json()['data']
                trusted = accounts.report_input(uid, attempt['id'])
                for question in trusted['quiz']['questions']:
                    r = await c.post('/api/v1/attempts/'+attempt['id']+'/answers', json={'question_id':question['id'],'selected':question['answers'],'elapsed_ms':1000}); r.raise_for_status()
                r = await c.post('/api/v1/period-reports', json={'days':'7'}); r.raise_for_status()
                report = r.json()['data']
                output['model'] = {'status':'passed','questions':len(attempt['quiz']['questions']),'cited_questions':sum(bool(q['source_ids']) for q in attempt['quiz']['questions']),'period_status':report['status'],'total':report['snapshot']['current']['totals']['total']}
        except Exception as e: output['model'] = {'status':'failed','code':getattr(e,'code',type(e).__name__),'message':str(e)[:160]}
        finally:
            accounts.delete_account(uid, identity); db.engine.dispose()
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=True,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources-only', action='store_true', help='Check public sources without invoking the model.')
    asyncio.run(main(parser.parse_args().sources_only))
