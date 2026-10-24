"""Reuse existing real test images; credentials remain in memory, no paid model calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import httpx
from sqlalchemy import select
from app.accounts.database import Database,User,Attempt
from app.config import Settings
from tests.knowledge_support import assert_database


def main():
    root=Path(__file__).resolve().parents[2]
    output=root/'docs/quiz-images/live-20261024/final-live'
    settings=Settings(database_testing=True)
    database=Database(settings)
    with database.engine.connect() as connection:assert_database(settings,connection)
    with database.session() as session:
        row=session.scalar(select(Attempt).where(Attempt.completed_at.is_not(None)).order_by(Attempt.completed_at.desc()))
        assert row and row.quiz['image_generation']['generated']==5
        user=session.get(User,row.user_id)
        assert user.appid=='isolated-real-images'
        code,uid,attempt_id,quiz_id=user.openid,user.id,row.id,row.quiz_id
        expected=[q['image_url'] for q in row.quiz['questions']]
    with httpx.Client(base_url='http://127.0.0.1:18001',timeout=15,trust_env=False) as client:
        def login():
            response=client.post('/api/v1/auth/wechat',json={'code':code,'agreement_version':'2026-10-12'})
            assert response.status_code==200
            result=response.json()['data'];assert result['user']['id']==uid
            client.headers['Authorization']='Bearer '+result['token']
            return result['token']
        first=login()
        # The original real report may finish after its basic results are visible.
        for _ in range(30):
            restored=client.get('/api/v1/attempts/'+attempt_id).json()['data']
            if restored.get('report'):break
            time.sleep(.5)
        assert restored.get('report')
        before=client.get('/api/v1/quiz/images/capabilities').json()['data']['remaining']
        replay=client.post('/api/v1/attempts',json={'quiz_id':quiz_id})
        assert replay.status_code==200
        replay=replay.json()['data']
        assert [q['image_url'] for q in replay['quiz']['questions']]==expected
        second=login()
        restored=client.get('/api/v1/attempts/'+attempt_id).json()['data']
        assert [q['image_url'] for q in restored['quiz']['questions']]==expected
        after=client.get('/api/v1/quiz/images/capabilities').json()['data']['remaining']
        metrics=client.get('/__live_metrics').json()
        assert before==after==15 and len(metrics['image_calls'])==5
        assert all(item['http_status']==200 for item in metrics['image_calls'])
        report={'user_id':uid,'quota_before_reuse':before,'quota_after_reuse':after,'image_requests':5,
            'relogin_same_identity':True,'history_reuses_urls':True,'replay_reuses_urls':True,
            'image_urls':expected,'maximum_concurrency':metrics['maximum_concurrency']}
        (output/'reuse-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        env=os.environ.copy()
        env.update(LEVELUP_IMAGE_LIVE_TOKEN=second,LEVELUP_IMAGE_FIRST_URL=expected[0])
        command=[shutil.which('node'),str(root/'frontend/node_modules/@playwright/test/cli.js'),
            'test','--config=playwright.images-live.config.ts','--grep','既有真实图片','--reporter=line']
        process=subprocess.run(command,cwd=root/'frontend',env=env,capture_output=True,text=True,encoding='utf-8')
        safe_output=(process.stdout+'\n'+process.stderr).replace(first,'[redacted]').replace(second,'[redacted]')
        (output/'reuse-browser.txt').write_text(safe_output,encoding='utf-8')
        print(safe_output)
        assert process.returncode==0,'Browser reuse acceptance failed; inspect screenshots'
    database.engine.dispose()


if __name__=='__main__':main()
