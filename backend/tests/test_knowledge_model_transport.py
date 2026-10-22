import asyncio
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.config import Settings
from app.llm import ModelGateway


@pytest.mark.parametrize('name',['question_pipeline.QuestionPipeline','scopes.ScopePipeline','quizzes.QuizPipeline'])
def test_successive_sync_jobs_have_loop_owned_model_clients_and_close_them(monkeypatch,name):
    import importlib
    module,klass=name.split('.')
    pipeline_type=getattr(importlib.import_module('app.knowledge.'+module),klass)
    created=[]
    def model(**kwargs):
        client=kwargs.get('http_async_client')
        assert client is not None, 'Worker jobs must bypass process-global async client caching'
        assert not client.is_closed
        created.append((client,asyncio.get_running_loop()))
        return object()
    monkeypatch.setattr('app.llm.ChatOpenAI',model)
    pipeline=pipeline_type.__new__(pipeline_type)
    async def process(claim):
        ModelGateway(Settings(_env_file=None)).chat_model()
        # A separate counted gateway used by independent review shares only this job.
        from app.quiz_grounding.runtime import counted_gateway
        counted_gateway(Settings(_env_file=None),None,None,None).chat_model()
        await asyncio.sleep(0)
        return claim
    pipeline.process_async=process
    assert pipeline.process('first')=='first'
    assert pipeline.process('second')=='second'
    assert created[0][0] is created[1][0] and created[2][0] is created[3][0]
    assert created[0][0] is not created[2][0]
    assert all(client.is_closed for client,_ in created)
    assert created[0][1] is not created[2][1]


def test_client_context_does_not_escape_failed_job_or_touch_core_default(monkeypatch):
    from app.knowledge.question_pipeline import QuestionPipeline
    seen=[]
    monkeypatch.setattr('app.llm.ChatOpenAI',lambda **kw:seen.append(kw.get('http_async_client')))
    pipeline=QuestionPipeline.__new__(QuestionPipeline)
    async def broken(claim):
        ModelGateway(Settings(_env_file=None)).chat_model()
        raise ValueError('controlled')
    pipeline.process_async=broken
    with pytest.raises(ValueError): pipeline.process('failed')
    assert seen[0] is not None and seen[0].is_closed
    ModelGateway(Settings(_env_file=None)).chat_model()
    assert seen[-1] is None


def test_parallel_jobs_do_not_share_model_transport_between_worker_threads(monkeypatch):
    from app.knowledge.question_pipeline import QuestionPipeline
    seen=[]
    monkeypatch.setattr('app.llm.ChatOpenAI',lambda **kw:seen.append(kw.get('http_async_client')))
    def run(number):
        pipeline=QuestionPipeline.__new__(QuestionPipeline)
        async def process(claim):
            ModelGateway(Settings(_env_file=None)).chat_model()
            await asyncio.sleep(.02)
            return claim
        pipeline.process_async=process
        return pipeline.process(number)
    with ThreadPoolExecutor(max_workers=2) as pool: assert list(pool.map(run,range(4)))==list(range(4))
    assert len({id(c) for c in seen})==4 and all(c.is_closed for c in seen)
