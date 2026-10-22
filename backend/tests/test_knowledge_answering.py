from copy import deepcopy
import pytest
from app.errors import AppError
from app.quiz_grounding.snapshots import EvidenceSegment
from tests.test_knowledge_agent import source
from tests.test_grounding_generation import SequenceGateway


def draft(ids=None,text='实际资料支持的回答'):
    return {'status':'answered','paragraphs':[{'id':'p1','text':text,'source_ids':ids or ['kb-'+'a'*64]}]}


def review(status='supported',ids=None,**updates):
    return {'paragraphs':[{'paragraph_id':'p1','status':status,'source_ids':ids or ['kb-'+'a'*64],'reason':'独立核对结果'}],
            'goal_covered':True,'conflicts':[],**updates}


def outcome(values=None,**updates):
    from app.knowledge.retrieval import KnowledgeOutcome
    return KnowledgeOutcome(evidence=[source('实际原文支持的事实')] if values is None else values,**updates)


async def answer(gateway,result=None,**kwargs):
    from app.knowledge.answering import create_answer
    return await create_answer('按资料解释',result or outcome(),gateway,remaining=lambda:7-len(gateway.calls),**kwargs)


@pytest.mark.anyio
async def test_answer_has_paragraph_citations_and_separate_support_review():
    gateway = SequenceGateway([draft(),review()])
    result = await answer(gateway)
    assert result['status']=='answered' and result['paragraphs'][0]['source_ids']==['kb-'+'a'*64]
    assert result['sources'][0]['knowledge']['document_id']=='doc'
    assert result['grounding']['status']=='material_only'
    assert [schema for schema,_ in gateway.calls]==['AnswerDraft','AnswerReview']


@pytest.mark.anyio
async def test_no_sources_and_private_dependent_question_with_only_web_are_insufficient():
    gateway = SequenceGateway([])
    assert (await answer(gateway,outcome([])))['status']=='insufficient'
    web = EvidenceSegment(id='web',text='公开资料',url='https://example.com/',retrieved_at='2026-10-18T00:00:00Z',content_kind='snippet',supplement=True)
    result = await answer(gateway,outcome([web],depends_on_documents=True))
    assert result['status']=='insufficient' and not gateway.calls


@pytest.mark.anyio
@pytest.mark.parametrize('status',['unsupported','contradicted','ambiguous','off_scope'])
async def test_unsupported_claims_are_corrected_once_then_business_insufficient(status):
    gateway = SequenceGateway([draft(text='未支持的结论'),review(status),draft(text='仍未支持的结论'),review(status)])
    result = await answer(gateway)
    assert result['status']=='insufficient' and result['paragraphs']==[] and result['sources']==[]
    assert len(gateway.calls)==4 and '未支持' not in str(result)


@pytest.mark.anyio
async def test_forged_citations_and_missing_review_paragraphs_cannot_pass():
    for verdict in (review(ids=['forged']),review(paragraphs=[])):
        gateway = SequenceGateway([draft(ids=['forged']),verdict])
        from app.knowledge.answering import create_answer
        result = await create_answer('按资料回答',outcome(),gateway,remaining=lambda:0)
        assert result['status']=='insufficient' and not result['paragraphs']


@pytest.mark.anyio
async def test_conflicting_sources_can_be_described_separately_but_not_falsely_unified():
    first,second = source('资料 A: 比例为10%'),source('资料 B: 比例为20%')
    second = second.model_copy(update={'id':'second','knowledge':second.knowledge.model_copy(update={'document_id':'another'})})
    ids = [first.id,second.id]
    gateway = SequenceGateway([draft(ids,text='资料 A 给出10%，资料 B 给出20%，当前资料存在冲突。'),
        review(ids=ids,conflicts=[{'source_ids':ids,'reason':'数值冲突'}])])
    result = await answer(gateway,outcome([first,second]))
    assert result['status']=='answered' and result['conflicts'][0]['source_ids']==ids
    gateway = SequenceGateway([draft(ids,text='唯一比例为10%'),review('ambiguous',ids=ids)])
    from app.knowledge.answering import create_answer
    result = await create_answer('比例是多少',outcome([first,second]),gateway,remaining=lambda:0)
    assert result['status']=='insufficient'


@pytest.mark.anyio
async def test_network_failure_with_supported_private_material_is_honest_material_only():
    gateway = SequenceGateway([draft(),review()])
    result = await answer(gateway,outcome(reason_code='TAVILY_UNAVAILABLE'))
    assert result['status']=='answered' and result['grounding']['status']=='material_only'
    assert result['network']['reason_code']=='TAVILY_UNAVAILABLE'


@pytest.mark.anyio
async def test_public_answer_uses_actual_sources_and_index_failure_stays_technical():
    web = EvidenceSegment(id='web',text='公开原文支持回答',url='https://example.com/',retrieved_at='2026-10-18T00:00:00Z',content_kind='full_extract',supplement=True)
    gateway = SequenceGateway([draft(['web']),review(ids=['web'])])
    result = await answer(gateway,outcome([web],depends_on_documents=False))
    assert result['grounding']['status']=='source_backed' and result['grounding']['provider']=='tavily'
    assert result['network']['status']=='used'
    with pytest.raises(AppError) as error:
        await answer(SequenceGateway([]),outcome([],knowledge_error='KNOWLEDGE_INDEX_UNAVAILABLE'))
    assert error.value.status==503


@pytest.mark.anyio
async def test_saved_draft_restores_without_generating_a_second_answer():
    from app.knowledge.answering import create_answer
    checkpoints = {}
    async def read(name): return deepcopy(checkpoints.get(name))
    async def save(name,content): checkpoints[name]=deepcopy(content)
    interrupted = SequenceGateway([draft(),RuntimeError('process interrupted')])
    with pytest.raises(RuntimeError):
        await create_answer('问题',outcome(),interrupted,remaining=lambda:5,read_checkpoint=read,save_checkpoint=save)
    resumed = SequenceGateway([review()])
    result = await create_answer('问题',outcome(),resumed,remaining=lambda:4,read_checkpoint=read,save_checkpoint=save)
    assert result['status']=='answered' and [s for s,_ in resumed.calls]==['AnswerReview']


def test_answer_models_reject_oversized_answers_and_unreviewed_free_text():
    from app.knowledge.answering import AnswerDraft
    from pydantic import ValidationError
    value = draft(text='字'*1000)
    value['paragraphs'] *= 3
    with pytest.raises(ValidationError): AnswerDraft.model_validate(value)
    with pytest.raises(ValidationError): AnswerDraft.model_validate({**draft(),'raw_answer':'unverified bypass'})
