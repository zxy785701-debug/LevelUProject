"""Explicit paid cloud/H5 acceptance harness; isolated DB, local test login only."""
import argparse
from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

import uvicorn

from app.accounts.database import Database
from app.accounts.repository import Accounts
from app.config import Settings
from app.main import create_app
from app.question_images.config import ImageSettings
from app.question_images.provider import QwenImages
from app.question_images.service import QuestionImages
from app.question_images.storage import download_png
from tests.knowledge_support import assert_database
from tests.run_question_images_live import AuditTransport
from tests.test_mysql_accounts import WeChatStub


def serve(output,database_name=None):
    output.mkdir(parents=True,exist_ok=True)
    extra={'mysql_test_database':database_name} if database_name else {}
    settings=Settings(database_testing=True,tavily_api_key='',**extra,
        wechat_app_id='isolated-real-images',identity_hash_secret='isolated-live-image-acceptance-only',
        cors_origins=['http://127.0.0.1:18086'])
    database=Database(settings)
    with database.engine.connect() as connection:assert_database(settings,connection)
    database.migrate()
    accounts=Accounts(settings,database)
    config=ImageSettings()
    if config.unavailable_reason():raise RuntimeError(config.unavailable_reason())
    secrets=[config.api_key.get_secret_value(),config.cos_secret_id.get_secret_value(),config.cos_secret_key.get_secret_value()]
    metrics={'image_calls':[],'maximum_concurrency':0,'downloads':[]}
    lock=threading.Lock()
    class MeasuredProvider:
        active=0
        first_started=None
        async def generate(self,prompt,*,before_dispatch=None):
            # Explicit upper bound across the whole acceptance server run.
            if len(metrics['image_calls'])>=5:raise RuntimeError('Live acceptance image-call bound reached')
            record={'prompt':prompt}
            provider=QwenImages(config,transport=AuditTransport(record,secrets))
            started=None
            async def actual_dispatch():
                nonlocal started
                if before_dispatch:await before_dispatch()
                started=time.monotonic()
                if self.first_started is None:self.first_started=started
                record['dispatched_after_seconds']=round(started-self.first_started,3)
                self.active+=1
                metrics['maximum_concurrency']=max(metrics['maximum_concurrency'],self.active)
                metrics['image_calls'].append(record)
            try:
                return await provider.generate(prompt,before_dispatch=actual_dispatch)
            finally:
                if started is not None:
                    self.active-=1
                    record['elapsed_seconds']=round(time.monotonic()-started,2)
                (output/'cloud-metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')

    def capture(url,config):
        data=download_png(url,config)
        file='image-'+uuid4().hex+'.png'
        (output/file).write_bytes(data)
        with lock:metrics['downloads'].append(file)
        return data

    app=create_app(settings,accounts=accounts,wechat=WeChatStub())
    app.state.image_config=config
    app.state.images=QuestionImages(accounts,config,provider=MeasuredProvider(),download=capture)
    @asynccontextmanager
    async def isolated_lifespan(app):
        # Do not run global cleanup against other test fixtures or cloud objects.
        yield
        database.engine.dispose()
    app.router.lifespan_context=isolated_lifespan
    @app.get('/__live_metrics')
    def measurements():
        with lock:
            snapshot=json.loads(json.dumps(metrics))
        (output/'cloud-metrics.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        return snapshot
    uvicorn.run(app,host='127.0.0.1',port=18001,access_log=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--database',help='Dedicated isolated database ending in _test')
    args=parser.parse_args()
    serve(args.output,args.database)
