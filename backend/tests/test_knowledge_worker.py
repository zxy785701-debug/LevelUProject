import asyncio
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import pytest
from sqlalchemy import select
from app.errors import AppError
from tests.test_knowledge_repository import repo
from tests.test_knowledge_jobs import submit


@pytest.fixture
def anyio_backend(): return 'asyncio'


def test_directory_lock_refuses_a_second_process_and_releases_after_exit(repo):
    from app.knowledge.worker import DirectoryLock
    from app.knowledge.files import FileStore
    FileStore(repo.config.storage_root, create=True)
    script = '''
import sys
from app.knowledge.worker import DirectoryLock
try:
    with DirectoryLock(sys.argv[1]): print('acquired')
except Exception as error:
    print(getattr(error,'code',type(error).__name__))
    sys.exit(3)
'''
    def child():
        return subprocess.run([sys.executable,'-c',script,str(repo.config.storage_root)],
                              cwd=Path(__file__).resolve().parents[1], capture_output=True,text=True,timeout=30)
    with DirectoryLock(repo.config.storage_root):
        process = child()
        assert process.returncode == 3 and 'KNOWLEDGE_WORKER_LOCKED' in process.stdout
    assert child().returncode == 0


def test_database_lease_fences_stale_worker_even_on_different_process(repo):
    from app.knowledge.worker import WorkerGuard
    first, second = WorkerGuard(repo.accounts,repo.config,'first'), WorkerGuard(repo.accounts,repo.config,'second')
    first.acquire()
    with pytest.raises(AppError): second.acquire()
    from app.knowledge.database import WorkerLease
    with repo.database.session() as session:
        session.get(WorkerLease,first.identity).expires_at = repo.now()-timedelta(seconds=1)
    second.acquire()
    with pytest.raises(AppError): first.heartbeat()
    first.release()
    second.heartbeat()
    second.release()


@pytest.mark.anyio
async def test_bounded_worker_threads_leave_heartbeat_alive_and_prioritize_interaction(repo):
    from app.knowledge.worker import KnowledgeWorker
    from app.knowledge.jobs import DurableJobs
    from app.knowledge.database import Job, WorkerLease
    rows = [submit(repo,str(i)) for i in range(3)]
    with repo.database.session() as session:
        session.get(Job,rows[-1]['id']).priority = 10
    jobs = DurableJobs(repo.accounts,repo.config)
    started, ended = [], []
    gate = threading.Event()
    def handler(claim):
        started.append(claim.id)
        gate.wait(5)
        ended.append(claim.id)
        jobs.complete(claim,lambda session,row:{'ok':True})
    worker = KnowledgeWorker(repo.accounts,repo.config,handlers={'import':handler},poll_seconds=.03,heartbeat_seconds=.06)
    task = asyncio.create_task(worker.run())
    try:
        for _ in range(100):
            if len(started) == 2: break
            await asyncio.sleep(.03)
        assert len(started) == 2 and rows[-1]['id'] in started and not ended
        with repo.database.session() as session:
            before = session.get(WorkerLease,worker.guard.identity).heartbeat_at
        # MySQL's existing DATETIME columns store whole seconds.
        await asyncio.sleep(1.2)
        with repo.database.session() as session:
            after = session.get(WorkerLease,worker.guard.identity).heartbeat_at
        assert after > before
        gate.set()
        for _ in range(150):
            if len(ended) == 3: break
            await asyncio.sleep(.03)
        assert len(ended) == 3
    finally:
        gate.set()
        worker.stop()
        await asyncio.wait_for(task,10)
    assert all(jobs.get('alice',r['id'])['status'] == 'succeeded' for r in rows)


@pytest.mark.anyio
async def test_worker_errors_are_safe_and_disabled_entry_keeps_cleanup_processing(repo):
    from app.knowledge.worker import KnowledgeWorker
    from app.knowledge.jobs import DurableJobs
    calls = []
    row = submit(repo)
    def broken(claim): raise RuntimeError('private text and secret must never be logged')
    def cleanup(): calls.append('cleanup')
    # Entry is disabled in the fixture: it must still drain durable work/cleanup.
    worker = KnowledgeWorker(repo.accounts,repo.config,handlers={'import':broken},cleanup=cleanup,poll_seconds=.03)
    task = asyncio.create_task(worker.run())
    jobs = DurableJobs(repo.accounts,repo.config)
    try:
        for _ in range(150):
            if jobs.get('alice',row['id'])['status'] == 'failed': break
            await asyncio.sleep(.03)
        result = jobs.get('alice',row['id'])
        assert result['error_code'] == 'KNOWLEDGE_PROCESSING_FAILED'
        assert 'private' not in result['message'] and calls
    finally:
        worker.stop()
        await asyncio.wait_for(task,10)
