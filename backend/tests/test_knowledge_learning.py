import asyncio
import httpx
import pytest
from sqlalchemy import select,func
from app.errors import AppError
from tests.test_knowledge_repository import repo
from tests.test_knowledge_index import index
from tests.test_knowledge_quiz_publication import setup_quiz
from tests.helpers import quiz_payload,FakeGateway,REPORT


def test_knowledge_learning_report_replay_review_and_history_deletion_keep_core_behavior(index,repo):
    from app.accounts.database import Attempt,Quota,Reward
    from app.models import ReportRequest
    from app.services import generate_report
    pipeline,claim,gateway,queued,body = setup_quiz(repo,index)
    learning = pipeline.process(claim)
    aid = learning['id']
    for number,question in enumerate(quiz_payload()['questions']):
        result = repo.accounts.answer('alice',aid,{'question_id':question['id'],'selected':['B'] if number==0 else question['answers'],'elapsed_ms':1000})
    assert result['session']['completed_at'] and result['session']['quiz']['source']['segments']
    before = repo.accounts.me('alice')['stats']
    trusted = repo.accounts.report_input('alice',aid)
    report = asyncio.run(generate_report(ReportRequest.model_validate(trusted),repo.accounts.settings,FakeGateway(REPORT)))
    oid,_ = repo.accounts.reserve('alice','report','report',{'attempt_id':aid},aid)
    repo.accounts.model_call('alice',oid)
    repo.accounts.finish('alice',oid,report)
    assert repo.accounts.attempt('alice',aid)['report']['verification']['status']=='material_only'
    replay = repo.accounts.replay('alice',learning['quiz']['id'])
    assert replay['quiz']['source']['segments']==[] and replay['mode']=='replay'
    repo.accounts.answer('alice',replay['id'],{'question_id':'q0','selected':['A'],'elapsed_ms':100})
    review = repo.accounts.review('alice',[aid+':q0'])
    assert review['mode']=='review' and review['quiz']['source']['segments']==[]
    checked = repo.accounts.answer('alice',review['id'],{'question_id':review['quiz']['questions'][0]['id'],'selected':['A'],'elapsed_ms':100})
    assert checked['session']['quiz']['source']['segments'][0]['knowledge']['document_id']
    assert repo.accounts.me('alice')['stats']['xp']==before['xp']
    repo.accounts.delete_attempt('alice',aid)
    with pytest.raises(AppError): repo.accounts.attempt('alice',aid)
    result = pipeline.get('alice',queued['id'])
    assert result['result'] is None and result['error_code']=='KNOWLEDGE_RESULT_DELETED'
    from app.knowledge.database import Checkpoint,Job,PublishedResult
    with repo.database.session() as session:
        assert session.get(Job,queued['id']).result is None
        assert session.get(PublishedResult,claim.operation_id).result=={}
        assert session.scalar(select(func.count()).select_from(Checkpoint).where(Checkpoint.operation_id==claim.operation_id))==0
        assert session.get(Quota,'alice').quiz_count==1
        assert session.scalar(select(func.count()).select_from(Reward))==2


def test_new_quiz_source_delete_does_not_block_completed_history_but_blocks_new_publication(index,repo):
    from app.knowledge.cleanup import LibraryManagement
    pipeline,claim,gateway,queued,body = setup_quiz(repo,index)
    original_complete = pipeline.complete
    def delete_before_publish(claim,publish):
        LibraryManagement(repo.accounts,repo.config).delete_document('alice',claim.payload['documents'][0]['id'])
        return original_complete(claim,publish)
    pipeline.complete=delete_before_publish
    with pytest.raises(AppError): pipeline.process(claim)
    from app.accounts.database import Attempt
    with repo.database.session() as session: assert session.scalar(select(func.count()).select_from(Attempt))==0
