import asyncio
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.errors import AppError
from app.accounts.database import Operation, Quota
from tests.test_knowledge_repository import repo
from tests.test_knowledge_jobs import submit


def ai_job(repo, kind='question', key='qa'):
    from app.knowledge.database import Job
    with repo.database.session() as session:
        row = Job(id=str(uuid4()),user_id='alice',kind=kind,key=key,digest='a'*64,operation_id=str(uuid4()),
                  deadline_at=repo.now()+timedelta(seconds=180),payload={})
        session.add(row)
        session.flush()
        return row.id


def test_waiting_queue_never_blocks_core_ai_and_actual_calls_share_rate_limit(repo):
    from app.knowledge.budgets import JobBudgets
    jid = ai_job(repo)
    oid, _ = repo.accounts.reserve('alice','old-core','quiz',{})
    jobs = JobBudgets(repo.accounts,repo.config)
    claim = jobs.claim('worker')
    with pytest.raises(AppError) as error: jobs.model_call(claim,7)
    assert error.value.code == 'AI_BUSY'
    repo.accounts.finish('alice',oid,error='TEST_FINISHED')
    for _ in range(7): jobs.model_call(claim,7)
    with pytest.raises(AppError) as error: jobs.model_call(claim,7)
    assert error.value.code == 'KNOWLEDGE_BUDGET_EXHAUSTED'
    jobs.complete(claim,lambda s,j:{'answer':'test'})
    oid, _ = repo.accounts.reserve('alice','old-after','quiz',{})
    for _ in range(3): repo.accounts.model_call('alice',oid)
    with pytest.raises(AppError) as error: repo.accounts.model_call('alice',oid)
    assert error.value.code == 'AI_RATE_LIMIT'
    from app.knowledge.database import Usage
    with repo.database.session() as session:
        usage = session.scalar(select(Usage))
        quota = session.get(Quota,'alice')
        assert usage.questions == 1 and quota.quiz_count == 1


def test_model_retries_keep_core_quiz_charge_and_cancellation_releases_busy(repo):
    from app.knowledge.budgets import JobBudgets
    jid = ai_job(repo,'quiz')
    jobs = JobBudgets(repo.accounts,repo.config)
    first = jobs.claim('worker')
    jobs.model_call(first,7)
    jobs.fail(first,'TRANSIENT','重试',recoverable=True)
    second = jobs.claim('worker')
    jobs.model_call(second,7)
    jobs.cancel('alice',jid)
    with pytest.raises(AppError): jobs.model_call(second,7)
    with repo.database.session() as session:
        from app.accounts.database import User
        quota = session.get(Quota,session.get(User,'alice').identity)
        assert quota.quiz_count == 1 and len(quota.calls) == 2 and quota.busy_id is None
        operation = session.scalar(select(Operation).where(Operation.kind == 'quiz'))
        assert operation.model_calls == 2 and operation.charged == 1
    repo.accounts.reserve('alice','other-core','quiz',{})


def test_question_and_preparation_have_separate_daily_limits(repo):
    from app.knowledge.budgets import JobBudgets
    repo.config.question_daily_limit = 1
    repo.accounts.settings.topic_prepare_daily_limit = 1
    jobs = JobBudgets(repo.accounts,repo.config)
    for kind in ('question','prepare'):
        ai_job(repo,kind,kind+'1')
        claim = jobs.claim('worker')
        jobs.model_call(claim,7)
        jobs.complete(claim,lambda s,j:{'ok':True})
        ai_job(repo,kind,kind+'2')
        other = jobs.claim('worker')
        with pytest.raises(AppError) as error: jobs.model_call(other,7)
        assert error.value.status == 429
        jobs.cancel('alice',other.id)


def test_embedding_reservation_is_durable_separate_and_late_settlement_is_idempotent(repo):
    from app.knowledge.budgets import JobBudgets
    from app.knowledge.database import Usage
    repo.config.embedding_daily_tokens = 100
    submit(repo)
    jobs = JobBudgets(repo.accounts,repo.config)
    claim = jobs.claim('worker')
    jobs.reserve_embedding(claim,'request-one',70)
    jobs.reserve_embedding(claim,'request-one',70)
    with pytest.raises(AppError): jobs.reserve_embedding(claim,'request-two',40)
    jobs.cancel('alice',claim.id)
    jobs.settle_embedding(claim,'request-one',50)
    jobs.settle_embedding(claim,'request-one',50)
    with repo.database.session() as session:
        usage = session.scalar(select(Usage))
        assert usage.embedding_reserved == 0 and usage.embedding_actual == 50
        from app.accounts.database import User
        quota = session.get(Quota,session.get(User,'alice').identity)
        assert quota.quiz_count == 0 and not quota.calls and not quota.busy_id


def test_unconfirmed_embedding_response_keeps_reservation_on_restart(repo):
    from app.knowledge.budgets import JobBudgets
    from app.knowledge.database import Job, Usage
    repo.config.embedding_daily_tokens = 100
    submit(repo)
    jobs = JobBudgets(repo.accounts,repo.config)
    first = jobs.claim('first')
    jobs.reserve_embedding(first,'lost-response',70)
    with repo.database.session() as session: session.get(Job,first.id).lease_until = repo.now()-timedelta(seconds=1)
    second = jobs.claim('second')
    with pytest.raises(AppError): jobs.reserve_embedding(second,'retry-request',40)
    with repo.database.session() as session:
        assert session.scalar(select(Usage)).embedding_reserved == 70


def test_rate_wait_has_original_deadline_and_does_not_charge_unsent_requests(repo):
    from app.knowledge.budgets import JobBudgets
    ai_job(repo)
    jobs = JobBudgets(repo.accounts,repo.config)
    claim = jobs.claim('worker')
    now = repo.accounts.clock()
    oid, _ = repo.accounts.reserve('alice','busy','quiz',{})
    async def sleep(seconds): repo.accounts.clock = lambda: now+181
    with pytest.raises(AppError): asyncio.run(jobs.wait_model_call(claim,7,sleep=sleep))
    with repo.database.session() as session:
        from app.accounts.database import User
        quota = session.get(Quota,session.get(User,'alice').identity)
        assert quota.calls == []


def test_retrieval_cannot_spend_generation_review_reserve_or_reset_its_phase_budget(repo):
    from app.knowledge.budgets import JobBudgets
    ai_job(repo)
    jobs = JobBudgets(repo.accounts,repo.config)
    claim = jobs.claim('worker')
    for _ in range(3): jobs.model_call(claim,7,phase='retrieval',reserve=2)
    with pytest.raises(AppError): jobs.model_call(claim,7,phase='retrieval',reserve=2)
    for _ in range(4): jobs.model_call(claim,7)
    with pytest.raises(AppError): jobs.model_call(claim,7)
