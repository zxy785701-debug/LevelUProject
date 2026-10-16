import httpx
import pytest

from app.errors import AppError
from tests.helpers import FakeGateway, REPORT
from tests.test_mysql_accounts import system, login, generate, answer
from tests.test_multisource_accounts import FeatureGateway


@pytest.mark.anyio
async def test_learning_report_preserves_unverified_status_and_statistics(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        session = await generate(c)
        from tests.helpers import quiz_payload
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        system.state.gateway = FakeGateway(REPORT)
        report = await c.post('/api/v1/report/generate', json={'attempt_id': session['id']})
        assert report.status_code == 200, report.text
        data = report.json()['data']
        assert data['verification']['status'] == 'unverified'
        assert data['verification']['counts'] == {'unverified': 3}
        assert data['stats']['accuracy'] == 100 and data['stats']['xp'] == 30
        assert data['learning_scope']['domain'] == '网络协议'


@pytest.mark.anyio
async def test_report_cannot_upgrade_unverified_knowledge(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        session = await generate(c)
        from tests.helpers import quiz_payload
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        system.state.gateway = FakeGateway({**REPORT, 'summary': ['知识已经联网核实。', '继续学习。', '使用例子。']})
        response = await c.post('/api/v1/report/generate', json={'attempt_id': session['id']})
        assert response.status_code == 502 and response.json()['code'] == 'MODEL_INVALID_OUTPUT'
        assert (await c.get('/api/v1/attempts/' + session['id'])).json()['data']['report'] is None


@pytest.mark.anyio
async def test_period_snapshot_retains_sources_and_does_not_change_analytics(system):
    from tests.test_grounding_snapshots import sourced_quiz
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        info = await login(c)
        quiz = sourced_quiz()
        session = system.state.accounts.store_quiz(info['user']['id'], quiz)
        for q in quiz['questions']: await answer(c, session, q['id'], q['answers'])
        system.state.gateway = FeatureGateway()
        report = await c.post('/api/v1/period-reports', json={'days': '7'})
        assert report.status_code == 200, report.text
        data = report.json()['data']
        provenance = data['snapshot']['provenance'][0]
        assert provenance['verification']['status'] == 'source_backed'
        assert provenance['source']['segments'][0]['text'] == quiz['source']['segments'][0]['text']
        assert data['snapshot']['current']['totals']['total'] == 3
        assert data['snapshot']['current']['totals']['accuracy'] == 100
        assert 'real passage' not in system.state.gateway.calls[0]  # Model sees source metadata only.
        exported = (await c.get('/api/v1/period-reports/' + data['id'] + '/export')).json()['data']['text']
        assert '有来源支持' in exported


@pytest.mark.anyio
async def test_period_narrative_cannot_claim_unknown_or_unverified_sources_are_verified(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as c:
        await login(c)
        session = await generate(c)
        from tests.helpers import quiz_payload
        for q in quiz_payload()['questions']: await answer(c, session, q['id'], q['answers'])
        system.state.gateway = FakeGateway({'summary': ['所有知识已核实。'], 'findings': [], 'suggestions': []})
        response = await c.post('/api/v1/period-reports', json={'days': '7'})
        assert response.status_code == 502 and response.json()['code'] == 'MODEL_INVALID_OUTPUT'
