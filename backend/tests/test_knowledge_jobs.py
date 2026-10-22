from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from app.errors import AppError
from tests.test_knowledge_repository import repo


def submit(repo, key='job'):
    return repo.submit_file('alice', key, 'note.txt', b'Original content')


def test_only_one_connection_can_claim_the_same_job(repo):
    from app.knowledge.jobs import DurableJobs
    result = submit(repo)
    jobs = DurableJobs(repo.accounts, repo.config)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda n: jobs.claim('worker-'+str(n)), range(4)))
    claimed = [c for c in claims if c is not None]
    assert len(claimed) == 1 and claimed[0].id == result['id']
    assert claimed[0].fence == 1


def test_expired_lease_is_fenced_and_keeps_budget_deadline_and_progress(repo):
    from app.knowledge.jobs import DurableJobs
    result = submit(repo)
    jobs = DurableJobs(repo.accounts, repo.config)
    now = repo.accounts.clock()
    repo.accounts.clock = lambda: now
    first = jobs.claim('first-worker')
    jobs.consume(first, 'model_calls', 1, 7)
    jobs.checkpoint(first, 'parsed', {'text':'Original content'}, stage='embedding', progress=70)
    repo.accounts.clock = lambda: now + repo.config.lease_seconds + 1
    second = jobs.claim('second-worker')
    assert second.id == first.id and second.fence == first.fence + 1
    assert second.deadline_at == first.deadline_at
    assert second.budget['model_calls'] == 1
    assert jobs.read_checkpoint(second, 'parsed') == {'text':'Original content'}
    for action in (lambda: jobs.heartbeat(first), lambda: jobs.advance(first, 'publishing', 99), lambda: jobs.complete(first, lambda s,j: {'bad':True})):
        with pytest.raises(AppError): action()
    jobs.advance(second, 'parsing', 10)
    assert jobs.get('alice', result['id'])['progress'] == 70
    jobs.heartbeat(second)


def test_final_result_and_success_publish_in_one_transaction_exactly_once(repo):
    from app.knowledge.jobs import DurableJobs
    from app.knowledge.database import Document, PublishedResult
    result = submit(repo)
    jobs = DurableJobs(repo.accounts, repo.config)
    claim = jobs.claim('worker')
    def broken(session, job):
        session.get(Document, job.document_id).title = 'Must rollback'
        raise RuntimeError('simulated commit boundary failure')
    with pytest.raises(RuntimeError): jobs.complete(claim, broken)
    assert jobs.get('alice', result['id'])['status'] == 'running'
    assert repo.document('alice', result['document_id'])['title'] == 'note.txt'
    with repo.database.session() as s: assert s.get(PublishedResult, claim.operation_id) is None
    calls = []
    def publish(session, job):
        calls.append(job.id)
        return {'document_id':job.document_id}
    first = jobs.complete(claim, publish)
    assert jobs.complete(claim, publish) == first
    assert calls == [claim.id]
    assert jobs.get('alice', result['id'])['progress'] == 100


def test_recoverable_failures_are_bounded_and_cannot_refill_budget(repo):
    from app.knowledge.jobs import DurableJobs
    result = submit(repo)
    jobs = DurableJobs(repo.accounts, repo.config)
    for attempt in range(3):
        claim = jobs.claim('worker')
        assert claim.attempts == attempt + 1
        jobs.consume(claim, 'tool_calls', 1, 3)
        jobs.fail(claim, 'TRANSIENT', '请重试', recoverable=True)
    assert jobs.claim('worker') is None
    value = jobs.get('alice', result['id'])
    assert value['status'] == 'failed' and value['progress'] < 100


def test_expired_deadlines_and_queue_wait_end_with_actionable_failure(repo):
    from app.knowledge.jobs import DurableJobs
    from app.knowledge.database import Job
    result = submit(repo)
    with repo.database.session() as s:
        s.get(Job, result['id']).deadline_at = repo.now() - timedelta(seconds=1)
    jobs = DurableJobs(repo.accounts, repo.config)
    assert jobs.claim('worker') is None
    assert jobs.get('alice', result['id'])['error_code'] == 'KNOWLEDGE_JOB_EXPIRED'
    result = submit(repo,'queued')
    with repo.database.session() as s:
        s.get(Job,result['id']).created_at = repo.now() - timedelta(seconds=repo.config.queue_timeout_seconds+1)
    assert jobs.claim('worker') is None
    assert jobs.get('alice', result['id'])['error_code'] == 'KNOWLEDGE_QUEUE_TIMEOUT'


def test_restart_in_a_new_process_recovers_durable_budget_and_fence(repo):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from app.knowledge.database import Job
    result = submit(repo)
    script = '''
import json,sys
from app.config import Settings
from app.accounts.database import Database
from app.accounts.repository import Accounts
from app.knowledge.config import KnowledgeSettings
from app.knowledge.jobs import DurableJobs
database=Database(Settings(database_testing=True))
jobs=DurableJobs(Accounts(database.settings,database),KnowledgeSettings(_env_file=None,storage_root=sys.argv[1]))
claim=jobs.claim(sys.argv[2])
if sys.argv[2]=='first-process': jobs.consume(claim,'model_calls',1,7)
print(json.dumps({'id':claim.id,'fence':claim.fence,'budget':claim.budget,'deadline':claim.deadline_at.isoformat()}))
database.engine.dispose()
'''
    def run(owner):
        process = subprocess.run([sys.executable,'-c',script,str(repo.config.storage_root),owner],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=60)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)
    first = run('first-process')
    with repo.database.session() as s: s.get(Job,result['id']).lease_until = repo.now()-timedelta(seconds=1)
    second = run('restarted-process')
    assert first['id'] == second['id'] and second['fence'] == first['fence']+1
    assert second['budget']['model_calls'] == 1 and first['deadline'] == second['deadline']


def test_cancel_and_manual_retry_preserve_operation_and_stop_late_results(repo):
    from app.knowledge.jobs import DurableJobs
    result = submit(repo)
    jobs = DurableJobs(repo.accounts, repo.config)
    claim = jobs.claim('worker')
    jobs.consume(claim,'model_calls',1,7)
    jobs.advance(claim,'embedding',70)
    with pytest.raises(AppError) as error: jobs.cancel('bob',result['id'])
    assert error.value.status == 404
    cancelled = jobs.cancel('alice',result['id'])
    assert cancelled['status'] == 'cancelled' and cancelled['progress'] == 70
    assert jobs.cancel('alice',result['id']) == cancelled
    with pytest.raises(AppError): jobs.complete(claim,lambda s,j:{'late':True})
    retried = jobs.retry('alice',result['id'],'retry-key')
    assert retried['status'] == 'queued' and retried['progress'] == 70
    assert jobs.retry('alice',result['id'],'retry-key')['id'] == retried['id']
    assert jobs.retry('alice',result['id'],'another-key')['id'] == retried['id']
    resumed = jobs.claim('new-worker')
    assert resumed.operation_id == claim.operation_id and resumed.budget['model_calls'] == 1


def test_retry_cannot_reset_deadline_or_bypass_deleted_documents(repo):
    from app.knowledge.jobs import DurableJobs
    from app.knowledge.database import Document, Job
    result = submit(repo)
    jobs = DurableJobs(repo.accounts, repo.config)
    jobs.cancel('alice',result['id'])
    with repo.database.session() as s: s.get(Job,result['id']).deadline_at = repo.now()-timedelta(seconds=1)
    with pytest.raises(AppError): jobs.retry('alice',result['id'],'new-key')
    other = submit(repo,'other')
    jobs.cancel('alice',other['id'])
    with repo.database.session() as s: s.get(Document,other['document_id']).deleted_at = repo.now()
    with pytest.raises(AppError): jobs.retry('alice',other['id'],'new-key')


def test_deleted_account_cannot_control_or_publish_a_running_job(repo):
    from app.accounts.database import User
    from app.knowledge.jobs import DurableJobs
    jobs = DurableJobs(repo.accounts,repo.config)
    row = submit(repo)
    claim = jobs.claim('worker')
    with repo.database.session() as session: session.delete(session.get(User,'alice'))
    for call in (lambda: jobs.get('alice',row['id']), lambda: jobs.cancel('alice',row['id']),
                 lambda: jobs.retry('alice',row['id'],'retry'), lambda: jobs.complete(claim,lambda s,j:{'bad':True})):
        with pytest.raises(AppError): call()
