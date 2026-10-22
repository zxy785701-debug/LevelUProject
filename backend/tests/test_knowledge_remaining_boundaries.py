import asyncio
from pathlib import Path
from types import SimpleNamespace
from pydantic import SecretStr,ValidationError
import httpx
import pytest
from app.errors import AppError
from app.knowledge.files import FileStore,MARKER,validate_upload
from app.knowledge.config import KnowledgeSettings
from tests.test_knowledge_repository import repo
from tests.test_knowledge_index import index
from tests.test_knowledge_question_history import setup_question
from tests.test_knowledge_answering import draft,review
from tests.test_knowledge_embeddings import embedding
from tests.test_knowledge_boundaries import fails


def test_private_storage_rejects_relative_root_wrong_marker_and_write_failure(tmp_path,monkeypatch):
    fails('KNOWLEDGE_STORAGE_UNAVAILABLE',lambda:FileStore(Path('relative')))
    (tmp_path/MARKER).write_text('wrong signature')
    fails('KNOWLEDGE_STORAGE_UNAVAILABLE',lambda:FileStore(tmp_path))
    store=FileStore(tmp_path/'safe',create=True)
    real_open=Path.open
    def unavailable(path,*args,**kwargs):
        if path.suffix=='.bin': raise OSError('disk full')
        return real_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',unavailable)
    fails('KNOWLEDGE_STORAGE_UNAVAILABLE',lambda:store.save('alice',b'body'))
    store.delete_user('missing-account')
    fails('KNOWLEDGE_FILE_INVALID',lambda:validate_upload('bad.md',b'\xff',100))


def test_storage_symlink_race_and_account_bucket_are_rejected(tmp_path,monkeypatch):
    store=FileStore(tmp_path/'safe',create=True)
    relative=store.save('alice',b'body')
    real=Path.is_symlink
    monkeypatch.setattr(Path,'is_symlink',lambda p:True if p.name==FileStore.bucket('alice') else real(p))
    fails('KNOWLEDGE_FILE_PATH_INVALID',lambda:store.read('alice',relative))
    fails('KNOWLEDGE_FILE_PATH_INVALID',lambda:store.delete_user('alice'))
    monkeypatch.setattr(Path,'is_symlink',real)
    resolve=Path.resolve
    monkeypatch.setattr(Path,'resolve',lambda p,*a,**kw:tmp_path/'outside' if p.name.endswith('.bin') else resolve(p,*a,**kw))
    fails('KNOWLEDGE_FILE_PATH_INVALID',lambda:store.read('alice',relative))


def test_optional_storage_probe_errors_and_incoherent_heartbeat_disable_safely(tmp_path,monkeypatch):
    value=KnowledgeSettings(_env_file=None,enabled=True,embedding_api_key='fake',embedding_base_url='https://dashscope.aliyuncs.com/api/v1',storage_root=tmp_path)
    with pytest.raises(ValidationError): KnowledgeSettings(_env_file=None,heartbeat_seconds=20,lease_seconds=30)
    real=Path.exists
    def broken(path):
        if path==tmp_path: raise OSError('unavailable disk')
        return real(path)
    monkeypatch.setattr(Path,'exists',broken)
    assert value.unavailable_reason()=='KNOWLEDGE_STORAGE_UNAVAILABLE'


def test_actual_question_pipeline_checks_remaining_budget_on_correction(index,repo):
    pipeline,claim,gateway,selected,queued=setup_question(repo,index)
    sid=gateway.responses[0]['paragraphs'][0]['source_ids']
    gateway.responses=[draft(sid),review('unsupported',ids=sid),draft(sid,text='修正后有依据的表述'),review(ids=sid)]
    result=pipeline.process(claim)
    assert pipeline.question('alice',result['question_id'])['paragraphs'][0]['text']=='修正后有依据的表述'
    assert len(gateway.calls)==4


def test_question_pipeline_requires_real_model_configuration_after_retrieval(index,repo):
    pipeline,claim,gateway,selected,queued=setup_question(repo,index)
    pipeline.gateway=None; repo.accounts.settings.deepseek_api_key=SecretStr('')
    fails('MODEL_NOT_CONFIGURED',lambda:pipeline.process(claim))


def test_embedding_duplicate_cache_save_and_unreported_usage_are_conservative(embedding):
    from app.knowledge.database import Usage,EmbeddingCache
    from sqlalchemy import select
    adapter,state,jobs,claim=embedding
    first=adapter.embed_documents(['same content'])
    adapter._save(['same content'],[[0.5]*1024],'document')
    assert adapter.embed_documents(['same content'])[0]==pytest.approx(first[0])
    state['mutate']=lambda body:body.update(usage={'total_tokens':'unreported'})
    assert len(adapter.embed_documents(['new content']))==1
    with jobs.database.session() as session: assert session.scalar(select(Usage)).embedding_reserved>0


def test_embedding_oversized_or_invalid_json_response_is_never_cached(embedding):
    adapter,state,jobs,claim=embedding
    state['mutate']=lambda body:body.update(padding='x'*(2*1024*1024+1))
    fails('EMBEDDING_INVALID_RESPONSE',lambda:adapter.embed_documents(['oversized provider output']))
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'not JSON'))) as client:
        adapter.client=client
        fails('EMBEDDING_INVALID_RESPONSE',lambda:adapter.embed_documents(['invalid provider JSON']))


def test_runtime_dispatch_cleanup_close_and_unavailable_configuration(repo,monkeypatch):
    import app.knowledge.runtime as module
    closed=[]
    monkeypatch.setattr(module,'VectorIndex',lambda *a,**kw:SimpleNamespace(close=lambda:closed.append('closed')))
    runtime=module.WorkerRuntime(repo.accounts,repo.config,lock=None,guard=None)
    fails('EMBEDDING_NOT_CONFIGURED',lambda:runtime.process(SimpleNamespace(kind='question')))
    repo.config.embedding_api_key=SecretStr('fake'); repo.config.embedding_base_url='https://dashscope.aliyuncs.com/api/v1'
    for kind,handler in [('import',runtime.imports),('reindex',runtime.imports),('question',runtime.questions),('prepare',runtime.scopes),('quiz',runtime.quizzes)]:
        handler.process=lambda claim:claim.kind
        assert runtime.process(SimpleNamespace(kind=kind))==kind
    fails('KNOWLEDGE_JOB_UNSUPPORTED',lambda:runtime.process(SimpleNamespace(kind='unknown')))
    assert runtime.cleanup() is False
    runtime.close(); runtime.close(); assert closed==['closed']


def test_quiz_topic_duplicates_are_invalid_at_the_dto_boundary():
    from app.knowledge.models import QuizRequest
    with pytest.raises(ValidationError): QuizRequest(scope_id='scope',scope_version=1,candidate_ids=['a','a'])
