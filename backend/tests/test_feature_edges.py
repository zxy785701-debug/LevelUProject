import asyncio
from datetime import datetime, timedelta
import httpx
import pytest
from sqlalchemy import select
from app.accounts.database import MaterialJob, Material, PeriodReport, Quota, User, utcnow
from app.errors import AppError
from tests.test_mysql_accounts import system, login, generate, answer
from tests.test_multisource_accounts import FeatureGateway, upload
from tests.helpers import quiz_payload


@pytest.mark.anyio
async def test_cancel_persists_and_late_worker_cannot_save_material(system):
    from app.materials.api import process_material
    from app.materials.parsers import parse_document
    system.state.gateway = FeatureGateway()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        account = await login(c); uid = account['user']['id']
        job, fresh = system.state.features.create_job(uid, 'cancel', {'url': 'public'})
        assert fresh
        assert (await c.post('/api/v1/material-jobs/'+job['id']+'/cancel')).json()['data']['status'] == 'cancelled'
        await process_material(system.state, uid, job['id'], parse_document('a.txt', b'HTTP text'))
        assert len(system.state.gateway.calls) == 0
        with system.state.accounts.database.session() as s:
            assert list(s.scalars(select(Material).where(Material.user_id == uid))) == []
        await login(c, 'bob')
        assert (await c.get('/api/v1/material-jobs/'+job['id'])).status_code == 404


@pytest.mark.anyio
async def test_expired_job_recovery_cleanup_and_referenced_retention(system):
    system.state.gateway = FeatureGateway()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        account = await login(c); uid = account['user']['id']
        job, _ = system.state.features.create_job(uid, 'old', {})
        with system.state.accounts.database.session() as s: s.get(MaterialJob, job['id']).created_at = utcnow()-timedelta(days=1)
        assert (await c.get('/api/v1/material-jobs/'+job['id'])).json()['data']['error_code'] == 'OPERATION_EXPIRED'
        material = await upload(c)
        system.state.features.material(uid, material['id'], True)
        orphan = await upload(c, 'orphan', 'orphan')
        with system.state.accounts.database.session() as s:
            for mid in (material['id'], orphan['id']): s.get(Material, mid).created_at = utcnow()-timedelta(days=2)
        system.state.features.cleanup()
        assert (await c.get('/api/v1/materials/'+material['id'])).status_code == 200
        assert (await c.get('/api/v1/materials/'+orphan['id'])).status_code == 404


@pytest.mark.anyio
async def test_period_failure_retry_limit_cache_invalidation_and_daily_quota(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        account = await login(c); uid = account['user']['id']
        session = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        class Broken:
            async def generate(self, *args): raise AppError('MODEL_TIMEOUT', '模拟超时', 504)
        system.state.gateway = Broken()
        for i in range(3):
            response = await c.post('/api/v1/period-reports', json={'days':'7'})
            assert response.status_code == 504
        assert (await c.post('/api/v1/period-reports', json={'days':'7'})).status_code == 429
        records = (await c.get('/api/v1/period-reports')).json()['data']
        assert records[0]['attempts'] == 3 and records[0]['status'] == 'failed'
        assert (await c.get('/api/v1/attempts/'+session['id'])).json()['data']['completed_at']
        system.state.gateway = FeatureGateway()
        # Different requested content is a different snapshot, then the daily cap applies.
        assert (await c.post('/api/v1/period-reports', json={'days':'7','sections':['overview']})).status_code == 200
        assert (await c.post('/api/v1/period-reports', json={'days':'7','sections':['performance']})).status_code == 200
        assert (await c.post('/api/v1/period-reports', json={'days':'7','sections':['advice']})).status_code == 429
        assert (await c.post('/api/v1/period-reports', json={'days':'7','sections':['overview']})).status_code == 200


@pytest.mark.anyio
async def test_period_excludes_reviews_after_interval_end_and_reference_validation(system):
    from app.materials.services import period_narrative, PeriodNarrative
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c); session = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], ['B'])
        from app.accounts.database import Attempt, WrongRow
        with system.state.accounts.database.session() as s:
            s.get(Attempt, session['id']).completed_at = datetime(2026,1,2)
            row = s.scalar(select(WrongRow)); row.reviews = [{'at': '2026-02-01T00:00:00+00:00','correct': True}]
        result = system.state.analytics.snapshot((await c.get('/api/v1/me')).json()['data']['id'], 'custom','2026-01-02','2026-01-02',['advice'])
        assert result['knowledge']['topics'][0]['points'][0]['correct'] == 0
        from tests.helpers import FakeGateway
        with pytest.raises(AppError): await period_narrative(result, FakeGateway({'summary':['复习知识'], 'findings':[{'point_id':'invented','analysis':'没有依据'}], 'suggestions':[]}))
        with pytest.raises(ValueError): PeriodNarrative.model_validate({'summary':['提升了 99%'], 'findings':[], 'suggestions':[]})


@pytest.mark.anyio
async def test_period_process_interruption_becomes_retriable_failure(system):
    from app.materials.repository import Features
    from app.accounts.database import Operation
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        account = await login(c); uid = account['user']['id']; session = await generate(c)
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        snapshot = system.state.analytics.snapshot(uid,'7',None,None,['overview'])
        report = system.state.features.prepare_report(uid,snapshot)
        oid, _ = system.state.accounts.reserve(uid,'interrupted','period',{'report_id':report['id']},report['id'])
        system.state.accounts.model_call(uid,oid)
        with system.state.accounts.database.session() as s:
            quota = s.scalar(select(Quota).where(Quota.identity == s.get(User,uid).identity))
            quota.busy_until = 0
        # A reconstructed service must read persistent state and detect the lost worker.
        result = Features(system.state.accounts).report(uid,report['id'])
        assert result['status'] == 'failed' and result['error_code'] == 'OPERATION_EXPIRED'


@pytest.mark.anyio
async def test_public_link_jobs_and_persisted_upstream_failure(system, monkeypatch):
    import app.materials.api as material_api
    from app.materials.parsers import segments_checked
    monkeypatch.setattr(material_api,'validate_url',lambda url:url)
    system.state.gateway = FeatureGateway()
    class PublicSources:
        async def web(self,url): return segments_checked('公开文章',[{'text':'HTTP 请求独立。','url':url}],source_type='web',url=url)
        async def video(self,url,start,end):
            if start == 10: raise AppError('NO_READABLE_CONTENT','这个片段没有字幕',422)
            return segments_checked('公开视频',[{'text':'Cookie 保存状态。','start':start,'end':end}],source_type='video',url=url)
    system.state.sources = PublicSources()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url='http://test') as c:
        await login(c)
        for kind,url in [('web','https://example.com/article'),('video','https://www.bilibili.com/video/BV1example')]:
            response = await c.post('/api/v1/materials/'+kind,json={'url':url,'start':0,'end':5})
            assert response.status_code == 200
            state = (await c.get('/api/v1/material-jobs/'+response.json()['data']['id'])).json()['data']
            assert state['status'] == 'succeeded'
            assert (await c.get('/api/v1/materials/'+state['material_id'])).json()['data']['source_type'] == kind
        response = await c.post('/api/v1/materials/video',json={'url':'https://www.bilibili.com/video/BV1example','start':10,'end':15})
        job = (await c.get('/api/v1/material-jobs/'+response.json()['data']['id'])).json()['data']
        assert job['status'] == 'failed' and job['error_code'] == 'NO_READABLE_CONTENT'
