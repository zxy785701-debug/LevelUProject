"""The only process allowed to open the local Chroma index.

The OS lock lasts until every synchronous handler has stopped. MySQL leases
provide observable liveness and fence jobs after an ungraceful process exit.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import logging
import os
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from ..errors import AppError
from .database import WorkerLease
from .files import FileStore
from .jobs import DurableJobs
from .repository import KnowledgeRepository

logger = logging.getLogger(__name__)


def storage_identity(config):
    return hashlib.sha256(os.path.normcase(str(config.storage_root.resolve())).encode()).hexdigest()


class DirectoryLock:
    def __init__(self, root):
        self.root, self.stream = Path(root), None

    def __enter__(self):
        FileStore(self.root, create=True)
        path = self.root / '.worker.lock'
        if path.is_symlink():
            raise AppError('KNOWLEDGE_STORAGE_UNAVAILABLE', '知识库目录锁不可用', 503)
        stream = path.open('a+b')
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise AppError('KNOWLEDGE_WORKER_LOCKED', '已有执行器占用此知识库目录，请勿重复启动', 409) from None
        self.stream = stream
        return self

    def __exit__(self, *args):
        if self.stream:
            try:
                self.stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            finally:
                self.stream.close()
                self.stream = None


class WorkerGuard(KnowledgeRepository):
    def __init__(self, accounts, config, owner):
        super().__init__(accounts, config)
        self.owner, self.identity, self.fence = owner, storage_identity(config), None

    def acquire(self):
        with self.database.session() as session:
            now = self.now()
            session.execute(insert(WorkerLease).values(id=self.identity,owner=self.owner,fence=0,
                            expires_at=now,heartbeat_at=now).on_duplicate_key_update(id=self.identity))
            row = session.scalar(select(WorkerLease).where(WorkerLease.id == self.identity).with_for_update())
            if row.owner != self.owner and row.expires_at > now:
                raise AppError('KNOWLEDGE_WORKER_LOCKED', '知识库执行器仍在运行', 409)
            row.owner, row.fence = self.owner, row.fence+1
            row.heartbeat_at, row.expires_at = now, now+timedelta(seconds=self.config.lease_seconds)
            self.fence = row.fence

    def heartbeat(self):
        with self.database.session() as session:
            row = session.scalar(select(WorkerLease).where(WorkerLease.id == self.identity).with_for_update())
            if (row is None or row.owner != self.owner or row.fence != self.fence or row.expires_at <= self.now()):
                raise AppError('KNOWLEDGE_WORKER_STALE', '执行器租约已失效，请检查后重新启动', 409)
            row.heartbeat_at, row.expires_at = self.now(), self.now()+timedelta(seconds=self.config.lease_seconds)

    def release(self):
        with self.database.session() as session:
            row = session.scalar(select(WorkerLease).where(WorkerLease.id == self.identity).with_for_update())
            if row and row.owner == self.owner and row.fence == self.fence:
                # DATETIME(0) may round fractional seconds into the future.
                # Release must be observably expired before a successor starts.
                row.expires_at = self.now().replace(microsecond=0)


class KnowledgeWorker:
    def __init__(self, accounts, config, *, handlers, cleanup=None, finalize=None, poll_seconds=.25, heartbeat_seconds=None):
        self.accounts, self.config = accounts, config
        self.owner = str(uuid4())
        self.jobs, self.guard = DurableJobs(accounts,config), WorkerGuard(accounts,config,self.owner)
        self.handlers, self.cleanup = handlers, cleanup
        self.finalize = finalize
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds or config.heartbeat_seconds
        self.stopping = False
        self.active = {}

    def stop(self): self.stopping = True

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await asyncio.to_thread(self.guard.heartbeat)
            for claim in list(self.active.values()):
                try:
                    await asyncio.to_thread(self.jobs.heartbeat,claim)
                except AppError:
                    # Cancellation/fencing is checked again before each effect or publication.
                    pass

    async def _execute(self, claim, executor):
        try:
            handler = self.handlers.get(claim.kind)
            if handler is None:
                raise AppError('KNOWLEDGE_JOB_UNSUPPORTED', '执行器版本不支持此任务，请更新后重试', 503)
            await asyncio.get_running_loop().run_in_executor(executor,handler,claim)
        except Exception as error:
            code = error.code if isinstance(error,AppError) else 'KNOWLEDGE_PROCESSING_FAILED'
            message = error.message if isinstance(error,AppError) else '处理暂时失败，请检查服务状态后重试'
            logger.warning('job_failed job=%s kind=%s error_code=%s',claim.id,claim.kind,code)
            try:
                await asyncio.to_thread(self.jobs.fail,claim,code,message)
            except AppError:
                pass
        finally:
            self.active.pop(claim.id,None)

    async def run(self):
        self.stopping = False
        with DirectoryLock(self.config.storage_root) as directory_lock, ThreadPoolExecutor(max_workers=self.config.worker_concurrency) as executor:
            self.directory_lock = directory_lock
            await asyncio.to_thread(self.guard.acquire)
            tasks, heartbeat = set(), asyncio.create_task(self._heartbeat())
            try:
                next_cleanup = 0
                while not self.stopping:
                    if heartbeat.done():
                        await heartbeat
                    if self.cleanup and asyncio.get_running_loop().time() >= next_cleanup:
                        # Outbox cleanup always gets a turn before new imports, even with entry disabled.
                        await asyncio.to_thread(self.cleanup)
                        next_cleanup = asyncio.get_running_loop().time()+30
                    while len(self.active) < self.config.worker_concurrency and not self.stopping:
                        claim = await asyncio.to_thread(self.jobs.claim,self.owner)
                        if claim is None: break
                        self.active[claim.id] = claim
                        task = asyncio.create_task(self._execute(claim,executor))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                    await asyncio.sleep(self.poll_seconds)
                if tasks: await asyncio.gather(*tasks)
            finally:
                # Never release the index directory while a synchronous writer is still running.
                if tasks: await asyncio.gather(*tasks,return_exceptions=True)
                heartbeat.cancel()
                try: await heartbeat
                except (asyncio.CancelledError,AppError): pass
                if self.finalize: await asyncio.to_thread(self.finalize)
                await asyncio.to_thread(self.guard.release)


def main(argv=None):
    import argparse
    import json
    from .config import load_settings
    from .files import MARKER
    parser = argparse.ArgumentParser(description='LevelUp single-process personal knowledge executor')
    parser.add_argument('--check',action='store_true',help='Read configuration without opening the index or database')
    parser.add_argument('--status',action='store_true',help='Read the database worker heartbeat without opening the index')
    parser.add_argument('--test',action='store_true',help='Use the explicitly isolated test database')
    parser.add_argument('--run-for',type=float,help='Bounded smoke duration, allowed only with --test')
    args = parser.parse_args(argv)
    if args.run_for is not None and (not args.test or not 0 < args.run_for <= 30):
        parser.error('--run-for requires --test and a duration between 0 and 30 seconds')
    config, error = load_settings()
    reason = error or config.unavailable_reason()
    start = bool(config and ((config.storage_root/MARKER).is_file() or reason is None))
    state = {'enabled':bool(config and config.enabled),'start_worker':start,'reason_code':reason}
    if args.check:
        print(json.dumps(state))
        return 0
    logging.basicConfig(level=logging.INFO,format='[knowledge] %(message)s')
    if not config:
        logger.error('worker_unavailable error_code=%s',error)
        return 2
    from ..config import Settings
    from ..accounts.database import Database
    from ..accounts.repository import Accounts
    settings = Settings(database_testing=args.test)
    database = Database(settings)
    accounts = Accounts(settings,database)
    try:
        if args.status:
            with database.session() as session:
                row = session.get(WorkerLease,storage_identity(config))
                state['worker_running'] = bool(row and row.expires_at > KnowledgeRepository(accounts,config).now())
            print(json.dumps(state))
            return 0
        if not start:
            logger.info('worker_disabled error_code=%s',reason)
            return 0
        runtime = None
        runtime_lock = __import__('threading').Lock()
        def get_runtime():
            nonlocal runtime
            with runtime_lock:
                if runtime is None:
                    from .runtime import WorkerRuntime
                    runtime = WorkerRuntime(accounts,config,lock=worker.directory_lock,guard=worker.guard)
            return runtime
        def handle(claim): get_runtime().process(claim)
        def cleanup():
            # An empty fresh installation needs no vector client until actual work exists.
            from .database import Cleanup,Revision
            with database.session() as session:
                pending = session.scalar(select(Cleanup.id).where(Cleanup.status != 'succeeded').limit(1))
                old_staging = session.scalar(select(Revision.id).where(Revision.status == 'staging',Revision.created_at < KnowledgeRepository(accounts,config).now()-timedelta(hours=24)).limit(1))
            if pending or old_staging or runtime is not None: get_runtime().cleanup()
        def finalize():
            if runtime is not None: runtime.close()
        worker = KnowledgeWorker(accounts,config,handlers={k:handle for k in ('import','reindex','question','prepare','quiz')},cleanup=cleanup,finalize=finalize)
        async def serve():
            if args.run_for:
                async def stop_later():
                    await asyncio.sleep(args.run_for)
                    worker.stop()
                timer = asyncio.create_task(stop_later())
            try: await worker.run()
            finally:
                if args.run_for: timer.cancel()
        try:
            logger.info('worker_starting')
            asyncio.run(serve())
        except KeyboardInterrupt:
            pass
        finally:
            if runtime is not None: runtime.close()
            logger.info('worker_stopped')
        return 0
    except Exception as error:
        code = error.code if isinstance(error,AppError) else 'KNOWLEDGE_WORKER_START_FAILED'
        logger.error('worker_failed error_code=%s',code)
        return 2
    finally:
        database.engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
