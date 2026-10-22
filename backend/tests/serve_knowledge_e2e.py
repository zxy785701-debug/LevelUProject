"""Local acceptance harness: real isolated MySQL/Chroma, explicitly fake paid providers.

Run alone, never alongside pytest suites which reset the same test database.
The normal application does not import this module.
"""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import httpx
import uvicorn
from langchain_core.messages import AIMessage
from app.config import Settings
from app.main import create_app
from app.accounts.database import Database
from app.accounts.repository import Accounts
from app.knowledge.config import KnowledgeSettings
from app.knowledge.worker import KnowledgeWorker
from app.knowledge.runtime import WorkerRuntime
from app.knowledge.embeddings import BailianEmbeddings
from app.knowledge.retrieval_store import KnowledgeRetriever
from app.knowledge.retrieval import PublicWebPlan
from tests.knowledge_support import assert_database,assert_test_boundary
from tests.test_mysql_accounts import WeChatStub
from tests.serve_accounts_e2e import ScenarioGateway
from tests.test_knowledge_scopes import scope_content
from tests.test_grounding_agent import ScriptedModel


class KnowledgeGateway(ScenarioGateway):
    async def generate(self,schema,prompt,check=None):
        name = schema.__name__
        if name in ('AnswerDraft','AnswerReview','ScopeDraft'):
            data = json.loads(prompt.rsplit('\n数据:',1)[1])
            ids = [s['id'] for s in data['evidence']]
            if name == 'ScopeDraft': value={'status':'ready','scope':scope_content(ids[0])}
            elif name == 'AnswerDraft':
                value = {'status':'insufficient'} if '资料没有' in data['question'] else {'status':'answered','paragraphs':[{'id':'p1','text':data['evidence'][0]['text'][:900],'source_ids':ids[:1]}]}
            else: value={'paragraphs':[{'paragraph_id':p['id'],'status':'supported','source_ids':p['source_ids'],'reason':'受控界面测试审核'} for p in data['draft']['paragraphs']],'goal_covered':True,'conflicts':[]}
            result=schema.model_validate(value)
            if check: check(result)
            return result
        return await super().generate(schema,prompt,check)


def main():
    settings=Settings(database_testing=True,wechat_app_id='knowledge-e2e',identity_hash_secret='isolated-knowledge-e2e-secret-'*3,
        ai_minute_limit=1000,login_minute_limit=10000,quiz_daily_limit=100,topic_prepare_daily_limit=100,
        deepseek_api_key='',tavily_api_key='explicit-e2e-fake')
    database=Database(settings)
    with database.engine.connect() as connection: actual=assert_database(settings,connection)
    database.migrate()
    temporary=tempfile.TemporaryDirectory(prefix='levelup-knowledge-e2e-')
    root=Path(temporary.name)/'private-store'
    assert_test_boundary(settings,actual,root,Path(temporary.name))
    config=KnowledgeSettings(_env_file=None,enabled=True,storage_root=root,embedding_api_key='explicit-e2e-fake',
        embedding_base_url='https://dashscope.aliyuncs.com/api/v1',question_daily_limit=100)
    accounts=Accounts(settings,database)
    gateway=KnowledgeGateway()
    # Exercise the official Tavily SDK serialization without paid/network calls.
    import langchain_tavily._utilities
    import app.quiz_grounding.tavily as tavily
    tavily.resolved_ips=lambda host:['93.184.216.34']
    class Response:
        status=200
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def text(self): return json.dumps({'results':[{'url':'https://example.com/learn','title':'公开协议说明','raw_content':'HTTP 404 表示资源未找到。Cookie 用来保存状态。Session 保存会话信息。'}]})
    class Transport:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        def post(self,*args,**kwargs): return Response()
    langchain_tavily._utilities.aiohttp.ClientSession=Transport
    runtime=None
    initialization=threading.Lock()
    def get_runtime():
        nonlocal runtime
        with initialization:
            if runtime is None:
                runtime=WorkerRuntime(accounts,config,lock=worker.directory_lock,guard=worker.guard)
                def response(request):
                    # Equal vectors make the controlled test corpus retrievable;
                    # this harness does not claim semantic model validation.
                    body=json.loads(request.content)
                    return httpx.Response(200,json={'output':{'embeddings':[{'text_index':i,'embedding':[1.0]*1024} for i,_ in enumerate(body['input']['texts'])]},'usage':{'total_tokens':sum(len(t) for t in body['input']['texts'])}})
                def embeddings(claim): return BailianEmbeddings(accounts,config,claim,client=httpx.Client(transport=httpx.MockTransport(response)))
                runtime.imports.embedding_factory=embeddings
                for pipeline in (runtime.questions,runtime.scopes,runtime.quizzes):
                    pipeline.gateway=gateway
                    pipeline.retriever=KnowledgeRetriever(accounts,config,runtime.index,embedding_factory=embeddings,
                        model=ScriptedModel(replies=[AIMessage(content='done')]*100),public_plan=PublicWebPlan(safe_to_search=False))
            return runtime
    def handle(claim):
        time.sleep(2.5 if claim.kind in ('reindex','quiz') else .8)
        return get_runtime().process(claim)
    def cleanup():
        if runtime: get_runtime().cleanup()
    def close():
        if runtime: runtime.close()
    worker=KnowledgeWorker(accounts,config,handlers={k:handle for k in ('import','reindex','question','prepare','quiz')},cleanup=cleanup,finalize=close)
    app=create_app(settings,gateway,accounts=accounts,wechat=WeChatStub())
    app.state.knowledge_config=config
    original=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            task=asyncio.create_task(worker.run())
            try: yield
            finally:
                worker.stop()
                await task
                database.engine.dispose()
                temporary.cleanup()
    app.router.lifespan_context=lifespan
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('LEVELUP_KNOWLEDGE_E2E_PORT','8002')),access_log=False)


if __name__=='__main__': main()
