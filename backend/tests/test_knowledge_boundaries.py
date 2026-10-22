"""Recovery and rejection boundaries over the real isolated MySQL store."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import hashlib
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import delete,event,select
from sqlalchemy.orm import Session
from app.errors import AppError
from app.knowledge.database import Job,Revision,Document,Checkpoint,PublishedResult,Usage
from app.accounts.database import Operation,Quota
from app.knowledge.jobs import DurableJobs
from app.knowledge.budgets import JobBudgets
from tests.test_knowledge_repository import repo,seed
from tests.test_knowledge_jobs import submit
from tests.test_knowledge_budgets import ai_job


def fails(code,call):
    with pytest.raises(AppError) as caught: call()
    assert caught.value.code==code


def test_import_count_and_invalid_idempotency_keys_are_rejected_before_storage(repo):
    for key in ('',None,'x'*129): fails('INVALID_INPUT',lambda:repo.submit_file('alice',key,'a.md',b'body'))
    repo.config.max_documents=1
    submit(repo)
    fails('KNOWLEDGE_DOCUMENT_LIMIT',lambda:submit(repo,'second'))


def test_import_transaction_failure_removes_only_its_uncommitted_file(repo):
    def interrupt(session,*args):
        if any(isinstance(x,Job) for x in session.new): raise RuntimeError('injected commit failure')
    event.listen(Session,'before_flush',interrupt)
    try:
        with pytest.raises(RuntimeError): submit(repo)
    finally: event.remove(Session,'before_flush',interrupt)
    assert not list(repo.config.storage_root.rglob('*.bin'))


@pytest.mark.parametrize('content,code',[
    ({'source_type':'video','segments':[{'text':'transcript'}]},'UNSUPPORTED_FORMAT'),
    ({'source_type':'txt','segments':[{'text':'  '}]},'NO_READABLE_CONTENT')])
def test_material_copy_rejects_unsupported_or_empty_canonical_body(repo,content,code):
    from app.accounts.database import Material
    mid=str(uuid4())
    with repo.database.session() as session: session.add(Material(id=mid,user_id='alice',content={'title':'material',**content}))
    fails(code,lambda:repo.submit_material('alice','copy',mid))


def test_unpublished_broken_and_profile_changed_documents_cannot_be_selected(repo):
    fails('EMPTY_KNOWLEDGE_SCOPE',lambda:repo.select_documents('alice',[],all_ready=True))
    seed(repo,ready=False)
    fails('DOCUMENT_NOT_READY',lambda:repo.chunks('alice','doc'))
    with repo.database.session() as session:
        session.get(Document,'doc').active_revision_id='rev-doc'
        session.get(Document,'doc').status='ready'
    fails('DOCUMENT_NOT_READY',lambda:repo.chunks('alice','doc'))
    with repo.database.session() as session:
        revision=session.get(Revision,'rev-doc'); revision.status='ready'; revision.profile='different-profile'
    fails('KNOWLEDGE_REINDEX_REQUIRED',lambda:repo.select_documents('alice',['doc']))


def test_job_validation_and_root_checkpoint_updates_preserve_budget(repo):
    queued=submit(repo); jobs=DurableJobs(repo.accounts,repo.config); claim=jobs.claim('worker')
    fails('NOT_FOUND',lambda:jobs.lookup('alice','question','unknown'))
    fails('NOT_FOUND',lambda:jobs.processed_result(replace(claim,operation_id='foreign')))
    for value in (-1,100,True):
        with pytest.raises(ValueError): jobs.advance(claim,'embedding',value)
    with pytest.raises(ValueError): jobs.checkpoint(claim,'x',{},stage='x',progress=100)
    jobs.checkpoint(claim,'x',{'version':1},stage='parsing',progress=50)
    jobs.checkpoint(claim,'x',{'version':2},stage='parsing',progress=20)
    assert jobs.read_checkpoint(claim,'x')=={'version':2} and jobs.get('alice',queued['id'])['progress']==50
    for amount,limit in ((0,1),(True,1),(1,False)):
        with pytest.raises(ValueError): jobs.consume(claim,'tools',amount,limit)
    jobs.consume(claim,'tools',1,1)
    fails('KNOWLEDGE_BUDGET_EXHAUSTED',lambda:jobs.consume(claim,'tools',1,1))
    fails('INVALID_INPUT',lambda:jobs.retry('alice',queued['id'],''))
    assert jobs.retry('alice',queued['id'],'active')['id']==queued['id']


@pytest.mark.parametrize('reason',['deadline','attempts','deleted'])
def test_claim_terminalizes_unrecoverable_queued_work_without_execution(repo,reason):
    queued=submit(repo); jobs=DurableJobs(repo.accounts,repo.config)
    with repo.database.session() as session:
        row=session.get(Job,queued['id'])
        if reason=='deadline': row.deadline_at=repo.now()-timedelta(seconds=1)
        elif reason=='attempts': row.attempts=repo.config.job_max_attempts
        else: session.get(Document,row.document_id).deleted_at=repo.now()
    assert jobs.claim('worker') is None
    assert jobs.get('alice',queued['id'])['status']=='failed'


def test_existing_publication_is_reused_only_for_same_owner(repo):
    queued=submit(repo); jobs=DurableJobs(repo.accounts,repo.config); claim=jobs.claim('worker')
    with repo.database.session() as session: session.add(PublishedResult(operation_id=claim.operation_id,user_id='bob',kind='import',result={'safe':True}))
    fails('NOT_FOUND',lambda:jobs.complete(claim,lambda s,j:pytest.fail('must not publish')))
    with repo.database.session() as session: session.get(PublishedResult,claim.operation_id).user_id='alice'
    assert jobs.complete(claim,lambda s,j:pytest.fail('must reuse publication'))=={'safe':True}


def test_retry_identity_conflict_active_child_and_total_attempt_limit(repo):
    first=submit(repo); second=submit(repo,'second'); jobs=DurableJobs(repo.accounts,repo.config)
    jobs.cancel('alice',first['id'])
    fails('IDEMPOTENCY_CONFLICT',lambda:jobs.retry('alice',first['id'],'second'))
    child=jobs.retry('alice',first['id'],'recover')
    assert jobs.retry('alice',first['id'],'other')['id']==child['id']
    jobs.cancel('alice',child['id'])
    with repo.database.session() as session: session.get(Job,child['id']).attempts=repo.config.job_max_attempts
    fails('KNOWLEDGE_RETRY_LIMIT',lambda:jobs.retry('alice',child['id'],'exhausted'))


def test_language_operations_reject_import_and_already_succeeded_operation(repo):
    submit(repo); jobs=JobBudgets(repo.accounts,repo.config); claim=jobs.claim('worker')
    fails('INVALID_OPERATION',lambda:jobs.model_call(claim,7))
    jobs.cancel('alice',claim.id)
    ai_job(repo); claim=jobs.claim('worker'); jobs.model_call(claim,7)
    with pytest.raises(ValueError): jobs.yield_job(claim)
    with repo.database.session() as session: session.get(Operation,session.get(Job,claim.id).ai_operation_id).status='succeeded'
    fails('KNOWLEDGE_JOB_STALE',lambda:jobs.model_call(claim,7))


def test_publication_lease_validates_reviewed_operation_and_waits_boundedly(repo):
    instant=int(repo.accounts.clock())+.1; repo.accounts.clock=lambda:instant
    ai_job(repo,'quiz'); jobs=JobBudgets(repo.accounts,repo.config); claim=jobs.claim('worker')
    fails('KNOWLEDGE_QUIZ_NOT_REVIEWED',lambda:jobs.activate_for_publication(claim))
    jobs.model_call(claim,7)
    with repo.database.session() as session:
        row=session.get(Job,claim.id); operation=session.get(Operation,row.ai_operation_id)
        operation.status='succeeded'
    fails('KNOWLEDGE_RESULT_CONFLICT',lambda:jobs.activate_for_publication(claim))
    with repo.database.session() as session:
        session.get(Operation,session.get(Job,claim.id).ai_operation_id).status='failed'
        quota=session.get(Quota,'alice'); quota.busy_id='another-operation'; quota.busy_until=repo.accounts.clock()+60
    async def finish_other(delay):
        assert delay==1
        with repo.database.session() as session: session.get(Quota,'alice').busy_until=0
    asyncio.run(jobs.wait_publication(claim,sleep=finish_other))
    with repo.database.session() as session:
        quota=session.get(Quota,'alice'); quota.busy_id='busy'; quota.busy_until=repo.accounts.clock()+60
        session.get(Job,claim.id).deadline_at=repo.now()+timedelta(seconds=.5)
    fails('KNOWLEDGE_JOB_EXPIRED',lambda:asyncio.run(jobs.wait_publication(claim,sleep=finish_other)))


def test_wait_model_call_ends_at_original_deadline_and_propagates_other_errors(repo):
    instant=int(repo.accounts.clock())+.1; repo.accounts.clock=lambda:instant
    ai_job(repo); jobs=JobBudgets(repo.accounts,repo.config); claim=jobs.claim('worker')
    with repo.database.session() as session:
        quota=jobs.accounts._quota(session,'alice'); quota.busy_id='busy'; quota.busy_until=repo.accounts.clock()+60
        session.get(Job,claim.id).deadline_at=repo.now()+timedelta(seconds=.5)
    fails('KNOWLEDGE_JOB_EXPIRED',lambda:asyncio.run(jobs.wait_model_call(claim,7)))


def test_embedding_reservation_input_identity_and_settlement_guards(repo):
    submit(repo); jobs=JobBudgets(repo.accounts,repo.config); claim=jobs.claim('worker')
    for rid,tokens in (('',1),('r',0),('r',True),('x'*65,1)):
        with pytest.raises(ValueError): jobs.reserve_embedding(claim,rid,tokens)
    jobs.reserve_embedding(claim,'r',10)
    with pytest.raises(ValueError): jobs.reserve_embedding(claim,'r',11)
    for usage in (-1,True):
        with pytest.raises(ValueError): jobs.settle_embedding(claim,'r',usage)
    fails('KNOWLEDGE_RESERVATION_MISSING',lambda:jobs.settle_embedding(claim,'unknown',1))
    jobs.settle_embedding(claim,'r',8); jobs.settle_embedding(claim,'r',999)
    jobs.reserve_embedding(claim,'missing-usage',5)
    with repo.database.session() as session: session.execute(delete(Usage))
    fails('KNOWLEDGE_RESERVATION_MISSING',lambda:jobs.settle_embedding(claim,'missing-usage',1))
