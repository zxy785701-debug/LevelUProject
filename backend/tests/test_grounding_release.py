import httpx
import pytest
from tests.helpers import quiz_payload, FakeGateway, REPORT
from tests.test_mysql_accounts import system, login, generate, confirmed_body, answer


@pytest.mark.anyio
async def test_pause_new_feature_keeps_completed_recovery_answers_reports_and_replay(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as client:
        await login(client)
        session = await generate(client)
        original_body = await confirmed_body(client)
        system.state.settings.quiz_grounding_enabled = False
        disabled = await client.post('/api/v1/quiz/preparations', headers={'Idempotency-Key': 'paused'}, json={'text': 'HTTP'})
        assert disabled.status_code == 503 and disabled.json()['code'] == 'GROUNDING_DISABLED'
        disabled = await client.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'new-after-pause'}, json=original_body)
        assert disabled.status_code == 503 and disabled.json()['code'] == 'GROUNDING_DISABLED'
        restored = await client.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'first'}, json=original_body)
        assert restored.status_code == 200 and restored.json()['data']['status'] == 'succeeded'
        assert (await client.get('/api/v1/operations/first')).json()['data']['result']['id'] == session['id']
        assert (await client.get('/api/v1/quiz/preparations/' + original_body['preparation_id'])).json()['data']['status'] == 'ready'
        for question in quiz_payload()['questions']:
            assert (await answer(client, session, question['id'], question['answers'])).status_code == 200
        system.state.gateway = FakeGateway(REPORT)
        assert (await client.post('/api/v1/report/generate', json={'attempt_id': session['id']})).status_code == 200
        replay = await client.post('/api/v1/attempts', json={'quiz_id': session['quiz']['id']})
        assert replay.status_code == 200 and replay.json()['data']['mode'] == 'replay'
        assert len((await client.get('/api/v1/learning')).json()['data']['sessions']) == 2
        from tests.test_multisource_accounts import FeatureGateway
        system.state.gateway = FeatureGateway()
        job = await client.post('/api/v1/materials/document', headers={'Idempotency-Key': 'paused-legacy-material'}, files={'file': ('notes.txt', b'HTTP request and session basics', 'text/plain')})
        assert job.status_code == 200
        parsed = (await client.get('/api/v1/material-jobs/' + job.json()['data']['id'])).json()['data']
        assert parsed['status'] == 'succeeded'
        legacy = await client.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'paused-legacy-sync'}, json={'material_id': parsed['material_id'], 'question_count': 3})
        assert legacy.status_code == 200 and 'quiz' in legacy.json()['data'] and 'kind' not in legacy.json()['data']
