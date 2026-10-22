from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.quiz_grounding.snapshots import QuizSource,EvidenceSegment
from tests.test_knowledge_repository import repo,seed
from tests.helpers import quiz_payload


def knowledge_segment():
    return {'id':'kb-chunk','text':'Private actual support passage','content_kind':'material',
        'knowledge':{'document_id':'doc','revision_id':'rev-doc','chunk_id':'a'*64,'document_title':'原始笔记',
            'source_type':'md','document_version':1,'chunk_position':0,'header_path':['概念'],
            'start_index':0,'end_index':30}}


def test_old_snapshots_read_without_new_fields_and_knowledge_locations_are_strict():
    assert QuizSource(type='txt',title='old').segments == []
    source = QuizSource(type='knowledge_base',title='我的知识库',segments=[knowledge_segment()])
    assert source.segments[0].knowledge.header_path == ['概念']
    bad = knowledge_segment()
    bad['knowledge']['end_index'] = -1
    with pytest.raises(ValidationError): EvidenceSegment.model_validate(bad)
    bad = knowledge_segment()
    bad['knowledge']['collection'] = 'untrusted'
    with pytest.raises(ValidationError): EvidenceSegment.model_validate(bad)


def test_new_provenance_stays_hidden_until_answer_and_deleted_source_keeps_snapshot(repo):
    seed(repo)
    quiz = quiz_payload()
    quiz.update(id=str(uuid4()),created_at=datetime.now(timezone.utc).isoformat(),source_text='原始问题',difficulty='easy',
        source={'type':'knowledge_base','title':'我的知识库','segments':[knowledge_segment()]})
    for question in quiz['questions']: question['source_ids'] = ['kb-chunk']
    result = repo.accounts.store_quiz('alice',quiz)
    assert result['quiz']['source']['segments'] == []
    assert all(q['source_ids']==[] and q['answers']==[] for q in result['quiz']['questions'])
    question = quiz['questions'][0]
    result = repo.accounts.answer('alice',result['id'],{'question_id':question['id'],'selected':question['answers'],'elapsed_ms':1000})
    session = result['session']
    segment = session['quiz']['source']['segments'][0]
    assert segment['knowledge']['deleted'] is False
    from app.knowledge.cleanup import LibraryManagement
    LibraryManagement(repo.accounts,repo.config).delete_document('alice','doc')
    refreshed = repo.accounts.attempt('alice',session['id'])
    segment = refreshed['quiz']['source']['segments'][0]
    assert segment['knowledge']['deleted'] is True and segment['text']=='Private actual support passage'
    assert refreshed['quiz']['questions'][1]['source_ids']==[]


def test_index_hit_becomes_true_location_snapshot_including_web_as_stored_material():
    from app.knowledge.evidence import evidence_from_hit
    hit = {'chunk_id':'b'*64,'document_id':'doc','revision_id':'revision','version':2,'title':'原始网页',
        'source_type':'web','source':{'url':'https://example.com/','retrieved_at':'2026-10-01T00:00:00Z'},
        'text':'实际正文','location':{'start_index':20,'end_index':24,'header_path':[],'block':2,'page':3},'position':1}
    segment = evidence_from_hit(hit)
    assert segment.content_kind=='material' and segment.supplement is False
    assert segment.page==3 and segment.knowledge.document_version==2
    assert segment.knowledge.start_index==20 and segment.url=='https://example.com/'
