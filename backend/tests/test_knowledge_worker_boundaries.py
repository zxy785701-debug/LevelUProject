import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import SecretStr
from app.errors import AppError
from app.knowledge.worker import DirectoryLock,KnowledgeWorker,main
from app.knowledge.jobs import DurableJobs
from app.knowledge.database import Cleanup,Job
from tests.test_knowledge_repository import repo
from tests.test_knowledge_jobs import submit
from tests.test_knowledge_budgets import ai_job


def test_worker_release_is_immediately_expired_at_mysql_datetime_precision(repo):
    from app.knowledge.worker import WorkerGuard
    instant=int(repo.accounts.clock())+.9
    repo.accounts.clock=lambda:instant
    first=WorkerGuard(repo.accounts,repo.config,'first')
    first.acquire(); first.release()
    second=WorkerGuard(repo.accounts,repo.config,'second')
    second.acquire(); second.release()


def test_worker_cli_invalid_duration_disabled_bad_configuration_and_status(repo,monkeypatch,capsys):
    import app.knowledge.config as config
    monkeypatch.setattr(config,'load_settings',lambda:(repo.config,None))
    with pytest.raises(SystemExit) as error: main(['--run-for','1'])
    assert error.value.code==2
    assert main(['--test'])==0
    assert main(['--test','--status'])==0
    assert 'worker_running' in capsys.readouterr().out
    monkeypatch.setattr(config,'load_settings',lambda:(None,'KNOWLEDGE_CONFIGURATION_INVALID'))
    assert main([])==2


def test_cli_owns_one_runtime_and_closes_before_releasing_directory_lock(repo,monkeypatch):
    import app.knowledge.config as config
    import app.knowledge.runtime as runtime_module
    repo.config.enabled=True; repo.config.embedding_api_key=SecretStr('fake')
    repo.config.embedding_base_url='https://dashscope.aliyuncs.com/api/v1'
    monkeypatch.setattr(config,'load_settings',lambda:(repo.config,None))
    queued=submit(repo)
    with repo.database.session() as session: session.add(Cleanup(id=str(uuid4()),user_id='old-test-id',payload={'kind':'account','profiles':[]}))
    events=[]
    class Runtime:
        def __init__(self,accounts,configuration,*,lock,guard): self.lock=lock; self.closed=False; events.append('created')
        def process(self,claim):
            assert self.lock.stream is not None
            DurableJobs(repo.accounts,repo.config).complete(claim,lambda s,j:{'test':True}); events.append('processed')
        def cleanup(self): events.append('cleanup')
        def close(self):
            if not self.closed:
                assert self.lock.stream is not None
                self.closed=True; events.append('closed')
    monkeypatch.setattr(runtime_module,'WorkerRuntime',Runtime)
    assert main(['--test','--run-for','.8'])==0
    assert events.count('created')==events.count('closed')==1 and 'processed' in events and 'cleanup' in events
    assert DurableJobs(repo.accounts,repo.config).get('alice',queued['id'])['status']=='succeeded'


@pytest.mark.parametrize('exception',[KeyboardInterrupt(),AppError('KNOWLEDGE_WORKER_LOCKED','safe',409),RuntimeError('private provider body')])
def test_cli_shutdown_and_startup_failure_keep_safe_exit_codes(repo,monkeypatch,exception):
    import app.knowledge.config as config
    repo.config.enabled=True; repo.config.embedding_api_key=SecretStr('fake'); repo.config.embedding_base_url='https://dashscope.aliyuncs.com/api/v1'
    monkeypatch.setattr(config,'load_settings',lambda:(repo.config,None))
    async def broken(self): raise exception
    monkeypatch.setattr(KnowledgeWorker,'run',broken)
    assert main(['--test'])==(0 if isinstance(exception,KeyboardInterrupt) else 2)


def test_directory_lock_rejects_symlink_before_open_and_can_be_released_twice(repo,monkeypatch):
    real=Path.is_symlink
    monkeypatch.setattr(Path,'is_symlink',lambda path:True if path.name=='.worker.lock' else real(path))
    with pytest.raises(AppError) as caught:
        with DirectoryLock(repo.config.storage_root): pass
    assert caught.value.code=='KNOWLEDGE_STORAGE_UNAVAILABLE'
    DirectoryLock(repo.config.storage_root).__exit__()


@pytest.mark.anyio
async def test_unsupported_job_is_terminal_and_stale_error_cannot_overwrite_cancellation(repo,monkeypatch):
    queued=submit(repo); jobs=DurableJobs(repo.accounts,repo.config)
    worker=KnowledgeWorker(repo.accounts,repo.config,handlers={},poll_seconds=.01)
    serving=asyncio.create_task(worker.run())
    try:
        for _ in range(100):
            state=await asyncio.to_thread(jobs.get,'alice',queued['id'])
            if state['status']=='failed': break
            await asyncio.sleep(.02)
        assert state['error_code']=='KNOWLEDGE_JOB_UNSUPPORTED'
    finally: worker.stop(); await serving
    second=submit(repo,'cancelled')
    def cancelled(claim): jobs.cancel('alice',claim.id); raise RuntimeError('late failure')
    worker=KnowledgeWorker(repo.accounts,repo.config,handlers={'import':cancelled},poll_seconds=.01)
    serving=asyncio.create_task(worker.run())
    try:
        for _ in range(100):
            state=await asyncio.to_thread(jobs.get,'alice',second['id'])
            if state['status']=='cancelled': break
            await asyncio.sleep(.02)
        assert state['status']=='cancelled'
    finally: worker.stop(); await serving


@pytest.mark.anyio
async def test_lost_worker_heartbeat_stops_new_dispatch_and_releases_os_lock(repo,monkeypatch):
    worker=KnowledgeWorker(repo.accounts,repo.config,handlers={},poll_seconds=.01,heartbeat_seconds=.01)
    monkeypatch.setattr(worker.guard,'heartbeat',lambda:(_ for _ in ()).throw(AppError('KNOWLEDGE_WORKER_STALE','safe',409)))
    with pytest.raises(AppError): await worker.run()
    with DirectoryLock(repo.config.storage_root): pass
