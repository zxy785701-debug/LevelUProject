import json
import httpx
import pytest
from sqlalchemy import select
from app.accounts.database import Operation
from app.accounts.repository import digest
from app.models import GenerateRequest
from app.question_images.service import QuestionImages
from tests.helpers import FakeGateway, REPORT
from tests.test_mysql_accounts import system,login,confirmed_body,answer
from tests.test_multisource_accounts import FeatureGateway,upload
from tests.test_question_images_transport import config,png
from tests.test_question_images_service import Provider,Storage,Planner


class PlanningGateway(FeatureGateway):
    async def generate(self,schema,prompt,check=None):
        if schema.__name__=='VisualScenes':
            self.calls.append(prompt)
            result=schema.model_validate({'scenes':[{'question_id':f'q{i}',
                'description':f'A red apple beside {i+1} green leaves on a pale table.'} for i in range(3)]})
            if check:check(result)
            return result
        return await super().generate(schema,prompt,check)


def images(system,**values):
    c=config(**values)
    provider=Provider()
    system.state.image_config=c
    system.state.images=QuestionImages(system.state.accounts,c,provider=provider,storage=Storage(),download=lambda u,c:png(),planner=Planner())
    return provider


async def generated(c,key='image',**extra):
    body={**await confirmed_body(c,key),**extra}
    response=await c.post('/api/v1/quiz/generate',headers={'Idempotency-Key':key},json=body)
    assert response.status_code==200,response.text
    operation=(await c.get('/api/v1/operations/'+key)).json()['data']
    assert operation['status']=='succeeded',operation
    return operation['result'],body


@pytest.mark.anyio
async def test_capability_is_authenticated_and_reports_server_quota(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        assert (await c.get('/api/v1/quiz/images/capabilities')).status_code==401
        await login(c)
        provider=images(system)
        result=(await c.get('/api/v1/quiz/images/capabilities')).json()['data']
        assert result['available'] and result['remaining']==20 and result['daily_limit']==20
        assert result['resolution']=='512×512' and 'private-key' not in str(result)
        await generated(c,generate_images=True)
        result=(await c.get('/api/v1/quiz/images/capabilities')).json()['data']
        assert result['remaining']==17 and len(provider.prompts)==3


@pytest.mark.anyio
async def test_missing_and_invalid_image_configuration_only_disable_images(system,monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        monkeypatch.setenv('IMAGE_CONCURRENCY','invalid')
        result=(await c.get('/api/v1/quiz/images/capabilities')).json()['data']
        assert not result['available'] and result['reason_code']=='IMAGE_CONFIGURATION_INVALID'
        session,_=await generated(c,generate_images=True)
        assert len(session['quiz']['questions'])==3 and session['quiz']['image_generation']['generated']==0
        assert (await c.get('/api/v1/health')).status_code==200


@pytest.mark.anyio
async def test_unmigrated_image_tables_only_disable_optional_capability(system,monkeypatch):
    from app.question_images.repository import ImageRepository
    from sqlalchemy.exc import SQLAlchemyError
    images(system)
    def missing(*args):raise SQLAlchemyError('table missing')
    monkeypatch.setattr(ImageRepository,'quota',missing)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        result=(await c.get('/api/v1/quiz/images/capabilities')).json()['data']
        assert not result['available'] and result['reason_code']=='IMAGE_MIGRATION_REQUIRED'


@pytest.mark.anyio
async def test_topic_public_result_history_report_replay_and_wrongs_reuse_images(system):
    provider=images(system)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        identity=await login(c)
        session,body=await generated(c,generate_images=True)
        expected=[q['image_url'] for q in session['quiz']['questions']]
        assert all(expected) and all(not q['answers'] and not q['explanation'] for q in session['quiz']['questions'])
        assert (await c.post('/api/v1/quiz/generate',headers={'Idempotency-Key':'image'},json=body)).status_code==200
        assert len(provider.prompts)==3
        for q in session['quiz']['questions']:
            result=await answer(c,session,q['id'],['A'])
            assert result.status_code==200,result.text
        history=(await c.get('/api/v1/attempts')).json()['data']['items'][0]
        assert [q['image_url'] for q in history['quiz']['questions']]==expected
        replay=(await c.post('/api/v1/attempts',json={'quiz_id':session['quiz']['id']})).json()['data']
        assert [q['image_url'] for q in replay['quiz']['questions']]==expected
        review=(await c.post('/api/v1/attempts/review',json={'keys':[session['id']+':q1']})).json()['data']
        assert review['quiz']['questions'][0]['image_url']==expected[1]
        system.state.gateway=FakeGateway(REPORT)
        report=await c.post('/api/v1/report/generate',json={'attempt_id':session['id']})
        assert report.status_code==200,report.text
        await login(c)
        assert (await c.get('/api/v1/me')).json()['data']['id']==identity['user']['id']
        restored=(await c.get('/api/v1/attempts/'+session['id'])).json()['data']
        assert [q['image_url'] for q in restored['quiz']['questions']]==expected and len(provider.prompts)==3


@pytest.mark.anyio
async def test_default_off_preserves_old_idempotency_digest(system):
    provider=images(system)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        _,body=await generated(c)
        legacy=GenerateRequest.model_validate(body).model_dump()
        legacy.pop('generate_images')
        legacy.pop('candidate_ids')
        with system.state.accounts.database.session() as s:
            row=s.scalar(select(Operation).where(Operation.key=='image'))
            assert row.digest==digest(json.dumps(legacy,ensure_ascii=False,sort_keys=True))
        again=await c.post('/api/v1/quiz/generate',headers={'Idempotency-Key':'image'},json={**body,'generate_images':False})
        assert again.status_code==200 and not provider.prompts
        conflict=await c.post('/api/v1/quiz/generate',headers={'Idempotency-Key':'image'},json={**body,'generate_images':True})
        assert conflict.status_code==409


@pytest.mark.anyio
@pytest.mark.parametrize('execution',['sync','background'])
async def test_material_sync_and_background_both_support_images(system,execution):
    provider=images(system)
    system.state.gateway=FeatureGateway()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        material=await upload(c)
        response=await c.post('/api/v1/quiz/generate',headers={'Idempotency-Key':'material-image'},json={
            'material_id':material['id'],'point_ids':['s1'],'question_count':3,'execution':execution,'generate_images':True})
        assert response.status_code==200,response.text
        result=response.json()['data'] if execution=='sync' else (await c.get('/api/v1/operations/material-image')).json()['data']['result']
        assert all(q['image_url'] for q in result['quiz']['questions']) and len(provider.prompts)==3


@pytest.mark.anyio
async def test_image_timeout_and_quota_exhaustion_still_publish_text(system):
    images(system,IMAGE_DAILY_LIMIT=2,IMAGE_STAGE_TIMEOUT_SECONDS=.4)
    system.state.images.provider=Provider(delay=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        first,_=await generated(c,generate_images=True)
        assert first['quiz']['image_generation']['generated']==0
        assert len(first['quiz']['questions'])==3
        second,_=await generated(c,'another',generate_images=True)
        assert second['quiz']['image_generation']['reason_code']=='IMAGE_DAILY_LIMIT'
        assert len(system.state.images.provider.prompts)==2


@pytest.mark.anyio
async def test_visual_plan_uses_existing_generation_model_budget(system):
    provider=images(system)
    system.state.images.planner=None
    system.state.gateway=PlanningGateway()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        result,_=await generated(c,generate_images=True)
        assert result['quiz']['image_generation']['generated']==3
        with system.state.accounts.database.session() as s:
            row=s.scalar(select(Operation).where(Operation.key=='image'))
            assert row.model_calls==3  # Draft, review, one batch plan.
        assert len(provider.prompts)==3 and all('第 ' not in p for p in provider.prompts)


@pytest.mark.anyio
async def test_exhausted_text_model_budget_only_disables_images(system):
    provider=images(system)
    system.state.images.planner=None
    system.state.gateway=PlanningGateway()
    system.state.settings.generation_model_call_limit=2
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        result,_=await generated(c,generate_images=True)
        assert len(result['quiz']['questions'])==3 and result['quiz']['image_generation']['generated']==0
        assert not provider.prompts
        with system.state.accounts.database.session() as s:
            row=s.scalar(select(Operation).where(Operation.key=='image'))
            assert row.model_calls==2
