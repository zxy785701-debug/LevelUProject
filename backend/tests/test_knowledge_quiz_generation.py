from copy import deepcopy
import pytest
from app.errors import AppError
from app.config import Settings
from app.models import GenerateRequest
from app.quiz_grounding.generation import generate_grounded,draft_prompt
from tests.test_grounding_generation import SequenceGateway,review
from tests.helpers import quiz_payload
from tests.test_knowledge_agent import source


def context():
    return {'knowledge_policy':'strict','material':None,'segments':[source('HTTP 404 means Not Found; Cookies retain state.').model_dump(mode='json')],
        'scope':{'input_text':'根据所选资料比较机制及应用','topic':'HTTP','domain':'网络协议','focus':'机制与应用',
            'points':['错误处理','会话状态'],'scope_point_ids':['p1','p2'],
            'selected_topics':[{'candidate_id':'t1','topic':'错误处理','domain':'HTTP','scope_point_ids':['p1']},
                               {'candidate_id':'t2','topic':'会话状态','domain':'HTTP','scope_point_ids':['p2']}]}}


async def run(gateway,ctx=None,budget=7):
    async def stage(value): pass
    return await generate_grounded(GenerateRequest(text='HTTP',question_count=3),ctx or context(),gateway,Settings(_env_file=None),
        stage=stage,remaining=lambda:budget-len(gateway.calls))


@pytest.mark.anyio
async def test_knowledge_quiz_has_explicit_strict_policy_and_real_snapshots_without_fake_material():
    ids = [context()['segments'][0]['id']]
    gateway = SequenceGateway([{'status':'ready','quiz':quiz_payload()},review(ids=ids)])
    result = await run(gateway)
    assert result['source']['type']=='knowledge_base' and 'material_id' not in result['source']
    assert result['source']['segments'][0]['knowledge']['document_id']=='doc'
    assert result['grounding']['status']=='material_only'
    assert '知识库' in gateway.calls[0][1] and '不能用外部常识' in gateway.calls[0][1]
    assert result['learning_scope']['selected_topics']==context()['scope']['selected_topics']


@pytest.mark.anyio
async def test_unsupported_knowledge_questions_cannot_use_old_general_topic_fallback():
    gateway = SequenceGateway([{'status':'ready','quiz':quiz_payload()},review(statuses=['unsupported']*3)])
    with pytest.raises(AppError) as error: await run(gateway,budget=3)
    assert error.value.code=='QUIZ_REVIEW_FAILED'


@pytest.mark.anyio
async def test_no_knowledge_evidence_is_rejected_before_model_and_missing_topic_coverage_fails():
    empty = context()
    empty['segments']=[]
    gateway = SequenceGateway([])
    with pytest.raises(AppError) as error: await run(gateway,empty)
    assert error.value.code=='INSUFFICIENT_KNOWLEDGE' and not gateway.calls
    verdict = review(ids=[context()['segments'][0]['id']])
    verdict['covered_point_ids']=['p1']
    gateway = SequenceGateway([{'status':'ready','quiz':quiz_payload()},verdict])
    with pytest.raises(AppError): await run(gateway,budget=3)


@pytest.mark.anyio
async def test_failed_network_does_not_mislabel_independently_supported_knowledge_as_unverified():
    ctx = context()
    ctx['supplement_failed']=True
    gateway = SequenceGateway([{'status':'ready','quiz':quiz_payload()},review(ids=[ctx['segments'][0]['id']])])
    result = await run(gateway,ctx)
    assert result['grounding']['status']=='material_only' and result['grounding']['reason_code']=='SUPPLEMENT_FAILED'


@pytest.mark.anyio
async def test_unused_public_sources_do_not_claim_network_support_for_knowledge_quiz():
    ctx = context()
    ctx['segments'].append({'id':'unused-web','text':'未用于题目的网页','url':'https://example.com/',
        'retrieved_at':'2026-10-18T00:00:00Z','content_kind':'snippet','supplement':True})
    gateway = SequenceGateway([{'status':'ready','quiz':quiz_payload()},review(ids=[ctx['segments'][0]['id']])])
    result = await run(gateway,ctx)
    assert result['grounding']['status']=='material_only' and result['grounding']['provider'] is None
    assert result['grounding']['retrieved_at'] is None
