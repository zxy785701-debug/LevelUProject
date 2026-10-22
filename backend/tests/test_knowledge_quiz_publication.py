from copy import deepcopy
import pytest
from sqlalchemy import select,func,event
from sqlalchemy.orm import Session
from app.errors import AppError
from tests.test_knowledge_repository import repo
from tests.test_knowledge_index import index
from tests.test_knowledge_scopes import setup_scope
from tests.test_grounding_generation import SequenceGateway,review
from tests.test_grounding_snapshots import sourced_quiz
from tests.helpers import quiz_payload


def setup_quiz(repo,index):
    from app.knowledge.quizzes import QuizPipeline
    scopes,claim,_,selected,_,_ = setup_scope(repo,index)
    sid = scopes.process(claim)['scope_id']
    body = {'scope_id':sid,'scope_version':1,'candidate_ids':['topic-0','topic-1'],
        'supplement':False,'question_count':3,'difficulty':'easy'}
    context = scopes.confirm_scope('alice',sid,1,body['candidate_ids'],supplement=False)
    verdict = review(ids=[context['segments'][0]['id']])
    verdict['covered_point_ids']=context['scope']['scope_point_ids']
    gateway = SequenceGateway([{'status':'ready','quiz':quiz_payload()},verdict])
    pipeline = QuizPipeline(repo.accounts,repo.config,index,gateway=gateway)
    queued = pipeline.submit_quiz('alice','quiz',body)
    return pipeline,pipeline.claim('worker'),gateway,queued,body


def test_optional_store_transaction_rolls_back_and_old_default_still_commits(repo):
    from app.accounts.database import QuizRow,Attempt
    quiz = sourced_quiz()
    with pytest.raises(RuntimeError):
        with repo.database.session() as session:
            repo.accounts.store_quiz('alice',quiz,session=session)
            raise RuntimeError('outer transaction rolls back')
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(QuizRow))==0
        assert session.scalar(select(func.count()).select_from(Attempt))==0
    assert repo.accounts.store_quiz('alice',quiz)['quiz']['id']==quiz['id']


def test_quiz_job_publishes_one_original_session_and_refreshes_after_answers(index,repo):
    from app.accounts.database import Quota,Attempt
    pipeline,claim,gateway,queued,body = setup_quiz(repo,index)
    assert pipeline.submit_quiz('alice','quiz',body)['id']==queued['id']
    result = pipeline.process(claim)
    assert result['quiz']['source']['type']=='knowledge_base' and result['quiz']['source']['segments']==[]
    assert all(q['answers']==[] for q in result['quiz']['questions'])
    assert pipeline.process(claim)['id']==result['id']
    with repo.database.session() as session:
        assert session.get(Quota,'alice').quiz_count==1
        assert session.scalar(select(func.count()).select_from(Attempt))==1
    original = quiz_payload()['questions'][0]
    answered = repo.accounts.answer('alice',result['id'],{'question_id':original['id'],'selected':original['answers'],'elapsed_ms':1000})['session']
    refreshed = pipeline.get('alice',queued['id'])['result']
    assert refreshed==answered and refreshed['quiz']['source']['segments'][0]['knowledge']['document_id']


def test_final_transaction_failure_reuses_validated_quiz_and_never_double_charges(index,repo):
    from app.knowledge.database import Job
    from app.accounts.database import Attempt,Quota
    pipeline,claim,gateway,queued,body = setup_quiz(repo,index)
    def fail(session):
        if any(isinstance(obj,Job) and obj.kind=='quiz' and obj.status=='succeeded' for obj in session.identity_map.values()):
            raise RuntimeError('final transaction failure')
    event.listen(Session,'before_commit',fail)
    try:
        with pytest.raises(RuntimeError): pipeline.process(claim)
    finally: event.remove(Session,'before_commit',fail)
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Attempt))==0
        assert session.get(Job,queued['id']).status=='running'
        assert session.get(Quota,'alice').quiz_count==1
    pipeline.fail(claim,'INTERRUPTED','恢复',recoverable=True)
    resumed = pipeline.claim('new-worker')
    pipeline.gateway = SequenceGateway([])
    result = pipeline.process(resumed)
    assert pipeline.process(resumed)['id']==result['id']
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Attempt))==1
        assert session.get(Quota,'alice').quiz_count==1


def test_cancel_and_source_deletion_prevent_late_quiz_publication(index,repo):
    from app.knowledge.cleanup import LibraryManagement
    from app.accounts.database import Attempt
    pipeline,claim,gateway,queued,body = setup_quiz(repo,index)
    pipeline.cancel('alice',queued['id'])
    with pytest.raises(AppError): pipeline.process(claim)
    with repo.database.session() as session: assert session.scalar(select(func.count()).select_from(Attempt))==0


def test_confirmation_rejects_changed_network_or_foreign_scope(index,repo):
    pipeline,claim,gateway,queued,body = setup_quiz(repo,index)
    with pytest.raises(AppError): pipeline.submit_quiz('alice','different',{**body,'supplement':True})
    with pytest.raises(AppError): pipeline.submit_quiz('bob','foreign',body)


def test_expired_lease_cannot_publish_and_new_fence_reuses_the_reviewed_quiz(index,repo):
    from datetime import timedelta
    from app.knowledge.database import Job
    from app.accounts.database import Attempt,Quota
    pipeline,claim,gateway,queued,body = setup_quiz(repo,index)
    activate = pipeline.wait_publication
    resumed = []
    async def take_over(old):
        with repo.database.session() as session: session.get(Job,old.id).lease_until=repo.now()-timedelta(seconds=1)
        resumed.append(pipeline.claim('new-worker'))
        await activate(old)
    pipeline.wait_publication=take_over
    with pytest.raises(AppError): pipeline.process(claim)
    with repo.database.session() as session: assert session.scalar(select(func.count()).select_from(Attempt))==0
    pipeline.wait_publication=activate
    pipeline.gateway=SequenceGateway([])
    result = pipeline.process(resumed[0])
    assert result['id']
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Attempt))==1
        assert session.get(Quota,'alice').quiz_count==1
