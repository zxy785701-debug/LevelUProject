from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select,func
from app.errors import AppError
from tests.test_knowledge_repository import repo
from tests.test_knowledge_index import index,staged


def test_delete_is_immediate_outbox_is_durable_and_cleanup_idempotent(index,repo):
    from app.knowledge.cleanup import LibraryManagement,CleanupManager
    from app.knowledge.database import Document,Cleanup,Revision,Chunk
    from app.knowledge.files import FileStore
    pipeline,claim,parsed,chunks = staged(repo)
    index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*1024])
    manager = LibraryManagement(repo.accounts,repo.config)
    manager.delete_document('alice',claim.document_id)
    manager.delete_document('alice',claim.document_id)
    with pytest.raises(AppError): repo.document('alice',claim.document_id)
    with pytest.raises(AppError): pipeline.complete(claim,lambda s,j:{'late':True})
    assert FileStore(repo.config.storage_root).read('alice',claim.payload['file_path'])
    with repo.database.session() as session: assert session.scalar(select(func.count()).select_from(Cleanup)) == 1
    cleanup = CleanupManager(repo.accounts,repo.config,index)
    assert cleanup.process_one()
    assert not cleanup.process_one()
    with pytest.raises(AppError): FileStore(repo.config.storage_root).read('alice',claim.payload['file_path'])
    assert index.collection('alice').count() == 0
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Chunk)) == 0
        assert session.get(Revision,parsed['revision_id']).text == ''


def test_cleanup_failure_retries_without_restoring_document(index,repo,monkeypatch):
    from app.knowledge.cleanup import LibraryManagement,CleanupManager
    from app.knowledge.database import Cleanup
    from app.knowledge.files import FileStore
    pipeline,claim,parsed,chunks = staged(repo)
    manager = LibraryManagement(repo.accounts,repo.config)
    manager.delete_document('alice',claim.document_id)
    cleanup = CleanupManager(repo.accounts,repo.config,index)
    original = FileStore.delete
    monkeypatch.setattr(FileStore,'delete',lambda *a:(_ for _ in ()).throw(OSError('private path secret')))
    assert cleanup.process_one()
    with repo.database.session() as session:
        row = session.scalar(select(Cleanup))
        assert row.status == 'queued' and row.error_code == 'KNOWLEDGE_CLEANUP_FAILED'
        row.lease_until = repo.now()-timedelta(seconds=1)
    monkeypatch.setattr(FileStore,'delete',original)
    assert cleanup.process_one()
    with pytest.raises(AppError): repo.document('alice',claim.document_id)


def test_account_deletion_records_outbox_before_cascade_and_removes_private_storage(index,repo):
    from app.knowledge.cleanup import CleanupManager
    from app.knowledge.database import Cleanup,Document
    from app.knowledge.files import FileStore
    pipeline,claim,parsed,chunks = staged(repo)
    index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*1024])
    # Exercise the existing public account deletion transaction, not a direct fixture delete.
    repo.accounts.delete_account('alice',{'openid':'alice'})
    with repo.database.session() as session:
        assert session.get(Document,claim.document_id) is None
        row = session.scalar(select(Cleanup))
        assert row.user_id == 'alice' and row.payload['kind'] == 'account'
    assert CleanupManager(repo.accounts,repo.config,index).process_one()
    assert not (repo.config.storage_root/'files'/FileStore.bucket('alice')).exists()
    assert index.collection_name('alice',repo.profile) not in [c.name for c in index.client.list_collections()]
    with pytest.raises(AppError): pipeline.complete(claim,lambda s,j:{'late':True})


def test_staging_garbage_collection_never_cleans_active_or_live_work(index,repo):
    from app.knowledge.cleanup import CleanupManager
    from app.knowledge.database import Revision,Job,Cleanup
    pipeline,claim,parsed,chunks = staged(repo)
    index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*1024])
    cleanup = CleanupManager(repo.accounts,repo.config,index)
    with repo.database.session() as session:
        session.get(Revision,parsed['revision_id']).created_at = repo.now()-timedelta(days=2)
    assert cleanup.collect_garbage() == 0
    pipeline.cancel('alice',claim.id)
    assert cleanup.collect_garbage() == 1
    assert cleanup.collect_garbage() == 0
    assert cleanup.process_one()
    assert index.collection('alice').count() == 0


def test_worker_runtime_drives_real_import_batches_with_controlled_embedding(repo,monkeypatch):
    from app.knowledge.worker import KnowledgeWorker
    from app.knowledge.runtime import WorkerRuntime
    from app.knowledge.embeddings import BailianEmbeddings
    from tests.knowledge_support import embedding_response
    from pydantic import SecretStr
    import asyncio
    repo.config.enabled = True
    repo.config.embedding_api_key = SecretStr('fake')
    repo.config.embedding_base_url = 'https://test.cn-beijing.maas.aliyuncs.com/api/v1'
    row = repo.submit_file('alice','runtime','runtime.txt',b'Grounded original knowledge.')
    client = httpx.Client(transport=httpx.MockTransport(embedding_response))
    original = BailianEmbeddings.__init__
    def init(self,*args,**kwargs): original(self,*args,client=client,sleep=lambda _:None,**kwargs)
    monkeypatch.setattr(BailianEmbeddings,'__init__',init)
    holder = {}
    def runtime():
        if 'value' not in holder:
            holder['value'] = WorkerRuntime(repo.accounts,repo.config,lock=worker.directory_lock,guard=worker.guard)
        return holder['value']
    worker = KnowledgeWorker(repo.accounts,repo.config,handlers={'import':lambda claim:runtime().process(claim)},poll_seconds=.03)
    async def run():
        task = asyncio.create_task(worker.run())
        try:
            for _ in range(300):
                if repo.document('alice',row['document_id'])['status'] == 'ready': break
                await asyncio.sleep(.03)
            assert repo.document('alice',row['document_id'])['status'] == 'ready'
        finally:
            worker.stop()
            await asyncio.wait_for(task,10)
    try: asyncio.run(run())
    finally:
        if holder: holder['value'].close()
        client.close()
