from contextlib import contextmanager
from datetime import timedelta
import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import select
from app.errors import AppError
from tests.knowledge_support import embedding_response
from tests.test_knowledge_repository import repo,seed
from tests.test_knowledge_jobs import submit


@pytest.fixture
def index(repo):
    from app.knowledge.index import VectorIndex
    from app.knowledge.worker import DirectoryLock,WorkerGuard
    with DirectoryLock(repo.config.storage_root) as lock:
        guard = WorkerGuard(repo.accounts,repo.config,'index-test')
        guard.acquire()
        value = VectorIndex(repo.accounts,repo.config,lock=lock,guard=guard)
        yield value
        value.close()
        guard.release()


def staged(repo):
    from app.knowledge.importing import ImportPipeline
    submit(repo)
    pipeline = ImportPipeline(repo.accounts,repo.config)
    claim = pipeline.claim('worker')
    parsed = pipeline.parse(claim)
    chunks = pipeline.split(claim,parsed)
    return pipeline,claim,parsed,chunks


def test_index_refuses_to_open_without_live_directory_and_database_locks(repo):
    from app.knowledge.index import VectorIndex
    from app.knowledge.worker import DirectoryLock,WorkerGuard
    guard = WorkerGuard(repo.accounts,repo.config,'index-test')
    guard.acquire()
    with pytest.raises(AppError): VectorIndex(repo.accounts,repo.config,lock=DirectoryLock(repo.config.storage_root),guard=guard)
    guard.release()


def test_real_chroma_upsert_manifest_and_only_active_owned_selection(index,repo):
    from app.knowledge.database import Revision,Document
    pipeline,claim,parsed,chunks = staged(repo)
    vector = [1.0]+[0.0]*1023
    index.upsert(claim,parsed['revision_id'],chunks,[vector]*len(chunks))
    index.upsert(claim,parsed['revision_id'],chunks,[vector]*len(chunks))
    assert index.verify(claim,parsed['revision_id'],[c['id'] for c in chunks]) == len(chunks)
    with repo.database.session() as session:
        document = session.get(Document,claim.document_id)
        document.active_revision_id,document.status = parsed['revision_id'],'ready'
        session.get(Revision,parsed['revision_id']).status = 'ready'
    selected = repo.select_documents('alice',[claim.document_id])
    results = index.search(claim,selected,vector)
    assert len(results) == 1 and results[0]['text'] == 'Original content'
    assert results[0]['document_id'] == claim.document_id
    assert index.search(claim,selected,[0.0,1.0]+[0.0]*1022) == []
    with pytest.raises(AppError): index.search(claim,[{'id':'foreign','revision_id':'x'}],vector)
    with repo.database.session() as session: session.get(Document,claim.document_id).deleted_at = repo.now()
    with pytest.raises(AppError): index.search(claim,selected,vector)


def test_manifest_rejects_missing_wrong_dimensions_and_wrong_profile(index,repo):
    pipeline,claim,parsed,chunks = staged(repo)
    with pytest.raises(AppError): index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*3])
    with pytest.raises(AppError): index.verify(claim,parsed['revision_id'],[c['id'] for c in chunks])
    from app.knowledge.database import Revision
    with repo.database.session() as session: session.get(Revision,parsed['revision_id']).profile = 'wrong-profile'
    with pytest.raises(AppError): index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*1024])


def test_real_collections_separate_users_with_identical_query_vectors(index,repo):
    from app.knowledge.importing import ImportPipeline
    from app.knowledge.database import Document,Revision
    pipeline,alice,parsed,chunks = staged(repo)
    vector = [1.0]*1024
    index.upsert(alice,parsed['revision_id'],chunks,[vector])
    repo.submit_file('bob','private','b.txt',b'Bob private sentinel')
    bob = pipeline.claim('worker')
    private = pipeline.parse(bob)
    private_chunks = pipeline.split(bob,private)
    index.upsert(bob,private['revision_id'],private_chunks,[vector])
    with repo.database.session() as session:
        for claim,content in [(alice,parsed),(bob,private)]:
            document = session.get(Document,claim.document_id)
            document.active_revision_id,document.status = content['revision_id'],'ready'
            session.get(Revision,content['revision_id']).status = 'ready'
    assert index.collection_name('alice',index.profile) != index.collection_name('bob',index.profile)
    results = index.search(alice,repo.select_documents('alice',[alice.document_id]),vector)
    assert [r['text'] for r in results] == ['Original content']


def test_chroma_payload_cannot_replace_mysql_text_or_smuggle_another_users_chunk(index,repo):
    from app.knowledge.database import Revision,Document
    pipeline,claim,parsed,chunks = staged(repo)
    vector = [1.0]+[0.0]*1023
    index.upsert(claim,parsed['revision_id'],chunks,[vector])
    with repo.database.session() as session:
        session.get(Revision,parsed['revision_id']).status = 'ready'
        document = session.get(Document,claim.document_id)
        document.active_revision_id,document.status = parsed['revision_id'],'ready'
    collection = index.collection('alice')
    collection.upsert(ids=[chunks[0]['id'],'forged-id'],embeddings=[vector,vector],documents=['invented index body','private body'],
        metadatas=[{'user_id':'alice','profile':index.profile,'document_id':claim.document_id,'revision_id':parsed['revision_id']}]*2)
    result = index.search(claim,repo.select_documents('alice',[claim.document_id]),vector)
    assert len(result)==1 and result[0]['text']=='Original content'


def test_import_batches_are_invisible_until_atomic_activation_and_resume_cache(index,repo):
    from app.knowledge.indexing import ImportIndexer
    from app.knowledge.embeddings import BailianEmbeddings
    from app.knowledge.database import Document,Revision
    repo.config.chunk_size,repo.config.chunk_overlap = 100,10
    repo.config.embedding_batch_size = 2
    repo.config.embedding_api_key = SecretStr('fake-only')
    repo.config.embedding_base_url = 'https://test.cn-beijing.maas.aliyuncs.com/api/v1'
    # Recreate the profile-specific adapter after configuration changes.
    index.profile = __import__('app.knowledge.repository',fromlist=['embedding_profile']).embedding_profile(repo.config)
    row = repo.submit_file('alice','long','long.md',('# 内容\n\n'+'连续正文知识。'*100).encode())
    requests = []
    def handler(request): requests.append(request); return embedding_response(request)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = ImportIndexer(repo.accounts,repo.config,index,embedding_factory=lambda claim:BailianEmbeddings(repo.accounts,repo.config,claim,client=client,sleep=lambda _:None))
    first = pipeline.claim('worker')
    pipeline.process(first)
    assert repo.document('alice',row['document_id'])['active_revision_id'] is None
    # Simulate a worker disappearing after one committed vector batch.
    pipeline = ImportIndexer(repo.accounts,repo.config,index,embedding_factory=lambda claim:BailianEmbeddings(repo.accounts,repo.config,claim,client=client,sleep=lambda _:None))
    for _ in range(30):
        claim = pipeline.claim('worker')
        assert claim is not None
        pipeline.process(claim)
        if pipeline.get('alice',row['id'])['status']=='succeeded': break
    final = repo.document('alice',row['document_id'])
    assert final['status']=='ready' and final['version']==1
    assert pipeline.get('alice',row['id'])['progress']==100
    with repo.database.session() as session:
        revision = session.get(Revision,final['active_revision_id'])
        assert revision.manifest['vector_count']==revision.manifest['chunk_count']
    assert len(requests) <= (final['chunk_count']+1)//2
    client.close()


def test_failed_reindex_preserves_previous_active_revision_and_final_delete_race(index,repo):
    from app.knowledge.indexing import ImportIndexer
    from app.knowledge.database import Document
    seed(repo)
    pipeline = ImportIndexer(repo.accounts,repo.config,index,embedding_factory=lambda claim:None)
    queued = pipeline.submit_reindex('alice','rebuild','doc')
    assert pipeline.submit_reindex('alice','rebuild','doc')['id']==queued['id']
    claim = pipeline.claim('worker')
    parsed = pipeline.parse(claim)
    chunks = pipeline.split(claim,parsed)
    pipeline.fail(claim,'EMBEDDING_UNAVAILABLE','服务不可用')
    assert repo.document('alice','doc')['active_revision_id']=='rev-doc'
    retried = pipeline.retry('alice',queued['id'],'retry-rebuild')
    claim = pipeline.claim('worker')
    index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*1024]*len(chunks))
    with repo.database.session() as session: session.get(Document,'doc').deleted_at = repo.now()
    with pytest.raises(AppError): pipeline.activate(claim,parsed,chunks)


@pytest.mark.parametrize('iteration',range(5))
def test_multi_document_search_keeps_relevant_smaller_document_in_candidate_pool(index,repo,iteration):
    from app.knowledge.importing import ImportPipeline
    from app.knowledge.database import Document,Revision
    repo.config.chunk_size,repo.config.chunk_overlap = 100,0
    pipeline = ImportPipeline(repo.accounts,repo.config)
    selections = []
    for number,body in enumerate(['\n'.join(f'Fact {n}: '+str(n)*90 for n in range(60)),'Required evidence in smaller document']):
        queued = repo.submit_file('alice','fair-'+str(number),'d'+str(number)+'.txt',body.encode())
        claim = pipeline.claim('worker')
        parsed = pipeline.parse(claim)
        chunks = pipeline.split(claim,parsed)
        vector = ([1.0,0.0] if number==0 else [.9,.1])+[0.0]*1022
        index.upsert(claim,parsed['revision_id'],chunks,[vector]*len(chunks))
        with repo.database.session() as session:
            session.get(Revision,parsed['revision_id']).status = 'ready'
            document = session.get(Document,queued['document_id'])
            document.status,document.active_revision_id = 'ready',parsed['revision_id']
        selections.append(queued['document_id'])
        if number==0: pipeline.complete(claim,lambda s,j:{'ok':True})
    trace = []
    original_collection = index.collection
    collection = original_collection('alice')
    class TracedCollection:
        def __getattr__(self,name): return getattr(collection,name)
        def query(self,**kwargs):
            result = collection.query(**kwargs)
            trace.append({'where':kwargs['where'],'ids':result['ids'][0][:2],'distances':result['distances'][0][:2]})
            return result
    index.collection = lambda *args,**kwargs:TracedCollection()
    result = index.search(claim,repo.select_documents('alice',selections),[1.0]+[0.0]*1023)
    if {r['document_id'] for r in result} != set(selections):
        import json
        pytest.fail(json.dumps({'selected':selections,'results':[(r['title'],r['score']) for r in result],'queries':trace,
            'indexed':[(did,len(index.collection('alice').get(where={'document_id':did})['ids'])) for did in selections]},indent=2))
    assert len(result)<=12


def test_only_selected_active_revision_is_retrieved_from_real_index(index,repo):
    from app.knowledge.indexing import ImportIndexer
    from app.knowledge.database import Document,Revision
    pipeline,first,parsed,chunks = staged(repo)
    vector = [1.0]*1024
    index.upsert(first,parsed['revision_id'],chunks,[vector])
    with repo.database.session() as session:
        document = session.get(Document,first.document_id)
        document.status,document.active_revision_id = 'ready',parsed['revision_id']
        session.get(Revision,parsed['revision_id']).status='ready'
    old = repo.select_documents('alice',[first.document_id])
    pipeline.complete(first,lambda s,j:{'ok':True})
    rebuilding = ImportIndexer(repo.accounts,repo.config,index)
    rebuilding.submit_reindex('alice','new-revision',first.document_id)
    second = rebuilding.claim('worker')
    updated = rebuilding.parse(second)
    updated_chunks = rebuilding.split(second,updated)
    index.upsert(second,updated['revision_id'],updated_chunks,[vector])
    rebuilding.activate(second,updated,updated_chunks)
    from tests.test_knowledge_budgets import ai_job
    ai_job(repo)
    query = rebuilding.claim('worker')
    selected = repo.select_documents('alice',[first.document_id])
    assert selected[0]['revision_id'] != old[0]['revision_id']
    assert {r['revision_id'] for r in index.search(query,selected,vector)}=={updated['revision_id']}
    with pytest.raises(AppError): index.search(query,old,vector)
