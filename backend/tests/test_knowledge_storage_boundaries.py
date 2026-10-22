from copy import deepcopy
from types import SimpleNamespace
import asyncio
import hashlib
import io
import pytest
from sqlalchemy import select
from app.errors import AppError
from app.knowledge.database import Document,Revision,Chunk,Checkpoint,EmbeddingCache
from app.knowledge.importing import ImportPipeline,fetch_web
from app.knowledge.parsing import canonical_content
from app.knowledge.embeddings import BailianEmbeddings
from tests.test_knowledge_repository import repo
from tests.test_knowledge_index import index,staged
from tests.test_knowledge_jobs import submit
from tests.test_knowledge_budgets import ai_job
from tests.test_knowledge_retrieval_store import ready
from tests.test_knowledge_boundaries import fails
from tests.test_knowledge_embeddings import embedding


def test_web_import_executes_actual_body_budget_and_rejects_summary_only(repo):
    from app.knowledge.database import Job
    queued=submit(repo); pipeline=ImportPipeline(repo.accounts,repo.config)
    with repo.database.session() as session: session.get(Job,queued['id']).payload={'source':'web','url':'https://example.com/'}
    claim=pipeline.claim('worker')
    class Source:
        settings=repo.accounts.settings
        tools=SimpleNamespace(resolve=lambda host:['93.184.216.34'])
        async def web(self,url,before_request=None):
            await before_request()
            return {'title':'actual page','source_type':'web','url':url,'segments':[{'text':'real body','content_kind':'full_extract','retrieved_at':'2026-10-18T00:00:00Z'}]}
    value=pipeline.parse(claim,sources=Source())
    assert value['text']=='real body'
    with repo.database.session() as session: assert session.get(Job,claim.id).budget['page_attempts']==1
    class Summary(Source):
        async def web(self,*a,**kw): return {'segments':[{'text':'summary','content_kind':'snippet'}]}
    fails('KNOWLEDGE_WEB_BODY_REQUIRED',lambda:asyncio.run(fetch_web('https://example.com/',Summary())))


def test_restored_parse_and_split_reject_corrupted_profile_and_nonstaging_revision(repo,monkeypatch):
    pipeline,claim,parsed,chunks=staged(repo)
    with repo.database.session() as session: session.get(Revision,parsed['revision_id']).profile='changed'
    fails('KNOWLEDGE_PROFILE_CHANGED',lambda:pipeline.parse(claim))
    with repo.database.session() as session:
        row=session.get(Revision,parsed['revision_id']); row.profile=pipeline.profile; row.status='ready'
        session.delete(session.get(Checkpoint,(claim.operation_id,'split')))
    fails('KNOWLEDGE_JOB_STALE',lambda:pipeline.split(claim,parsed))


def test_unknown_import_kind_cannot_reach_embedding_or_publish(repo):
    from app.knowledge.database import Job
    queued=submit(repo); pipeline=ImportPipeline(repo.accounts,repo.config)
    with repo.database.session() as session: session.get(Job,queued['id']).payload={'source':'client-controlled'}
    fails('INVALID_INPUT',lambda:pipeline.parse(pipeline.claim('worker')))


def test_empty_whitespace_blocks_and_total_canonical_text_limit():
    assert canonical_content({'segments':[{'text':' '},{'text':'real'}]},max_chars=10)['segments'][0]['block']==2
    fails('NO_READABLE_CONTENT',lambda:canonical_content({'segments':[]},max_chars=10))
    fails('MATERIAL_TOO_LARGE',lambda:canonical_content({'segments':[{'text':'a'*11}]},max_chars=10))


def test_upsert_compensates_a_real_delete_committed_during_vector_write(index,repo,monkeypatch):
    pipeline,claim,parsed,chunks=staged(repo)
    collection=index.collection('alice')
    upsert=collection.upsert
    def interrupted(**kw):
        upsert(**kw)
        with repo.database.session() as session: session.get(Document,claim.document_id).deleted_at=repo.now()
    monkeypatch.setattr(collection,'upsert',interrupted)
    monkeypatch.setattr(index,'collection',lambda uid:collection)
    with pytest.raises(AppError): index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*1024])
    assert collection.count()==0


def test_writer_lock_and_collection_identity_are_rechecked_on_every_effect(index,repo):
    collection=index.collection('alice')
    collection.modify(metadata={**collection.metadata,'owner':'wrong-owner'})
    fails('KNOWLEDGE_INDEX_PROFILE_MISMATCH',lambda:index.collection('alice'))
    fails('KNOWLEDGE_INDEX_PROFILE_MISMATCH',lambda:index.remove('alice',{'kind':'account'}))
    stream=index.directory_lock.stream
    index.directory_lock.stream=None
    try: fails('KNOWLEDGE_WORKER_LOCK_REQUIRED',lambda:index.collection('alice'))
    finally: index.directory_lock.stream=stream


def test_sql_chunk_mismatch_stops_vector_write(index,repo):
    pipeline,claim,parsed,chunks=staged(repo)
    changed=deepcopy(chunks); changed[0]['text']='client changed text'
    fails('KNOWLEDGE_CHUNK_MISMATCH',lambda:index.upsert(claim,parsed['revision_id'],changed,[[1.0]*1024]))
    assert index.collection('alice').count()==0


@pytest.mark.parametrize('case',['missing','dimension'])
def test_disk_vector_manifest_requires_present_valid_vectors(index,repo,monkeypatch,case):
    pipeline,claim,parsed,chunks=staged(repo)
    import numpy as np
    collection=SimpleNamespace(get=lambda **kw:{'ids':[chunks[0]['id']],'embeddings':None if case=='missing' else [np.array([1.0])]})
    monkeypatch.setattr(index,'collection',lambda uid:collection)
    fails('KNOWLEDGE_INDEX_INCOMPLETE' if case=='missing' else 'EMBEDDING_INVALID_RESPONSE',lambda:index.verify(claim,parsed['revision_id'],[chunks[0]['id']]))


def test_index_search_validates_input_and_reports_empty_storage_as_technical_failure(index,repo):
    selected=ready(repo,index); ai_job(repo); claim=index.jobs.claim('worker')
    for vector,maximum in (([1.0],12),([1.0]*1024,True),([1.0]*1024,13)):
        fails('INVALID_INPUT',lambda:index.search(claim,selected,vector,maximum=maximum))
    collection=index.collection('alice'); collection.delete(ids=collection.get()['ids'])
    fails('KNOWLEDGE_INDEX_UNAVAILABLE',lambda:index.search(claim,selected,[1.0]*1024))


@pytest.mark.parametrize('case',['too_many','bad_vector','no_vectors','zero_norm'])
def test_exact_fallback_is_bounded_and_never_trusts_corrupt_vectors(index,repo,monkeypatch,case):
    import numpy as np
    selected=ready(repo,index); ai_job(repo); claim=index.jobs.claim('worker')
    ids=['unknown']*257 if case=='too_many' else ['unknown']
    values=None if case=='no_vectors' else [np.array([1.0] if case=='bad_vector' else [0.0]*1024)]
    collection=SimpleNamespace(count=lambda:300,query=lambda **kw:{'ids':[[]],'distances':[[]]},get=lambda **kw:{'ids':ids,'embeddings':values})
    monkeypatch.setattr(index,'collection',lambda uid:collection)
    fails('KNOWLEDGE_INDEX_UNAVAILABLE',lambda:index.search(claim,selected,[1.0]*1024))


def test_embedding_corrupt_cache_missing_key_deadline_and_semaphore_are_honest(embedding):
    from pydantic import SecretStr
    adapter,state,jobs,claim=embedding
    adapter.embed_documents(['cached'])
    with jobs.database.session() as session:
        cache=session.scalar(select(EmbeddingCache)); cache.vector=[1.0]
    fails('EMBEDDING_CACHE_INVALID',lambda:adapter.embed_documents(['cached']))
    adapter.config.embedding_api_key=SecretStr('')
    fails('EMBEDDING_NOT_CONFIGURED',lambda:adapter.embed_documents(['new text']))
    adapter.config.embedding_api_key=SecretStr('fake')
    original=adapter._remaining
    adapter._remaining=lambda:0
    fails('KNOWLEDGE_JOB_EXPIRED',lambda:adapter._request(['new'],'document'))
    adapter._remaining=original
    adapter.limiter=SimpleNamespace(acquire=lambda **kw:False)
    fails('EMBEDDING_BUSY',lambda:adapter._request(['new'],'document'))
