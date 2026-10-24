from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.accounts.database import TopicPreparation, Operation
from app.accounts.repository import digest
from app.models import GenerateRequest
from app.quiz_grounding.models import ScopeContent, QuizDraftResult, QuizReview
from app.quiz_grounding.selection import topic_selection
from app.quiz_grounding.generation import review_decision
from tests.helpers import grounding_payload, quiz_payload
from tests.test_grounding_generation import context, review
from tests.test_mysql_accounts import system, login, confirmed_body


def topics():
    data = grounding_payload(ScopeContent, '')
    second = deepcopy(data['candidates'][0])
    second.update(id='culture', topic='文化', domain='民族文化')
    data['candidates'].append(second)
    return ScopeContent.model_validate(data)


def test_topic_selection_balances_all_topics_with_colliding_local_point_ids():
    scope = topics()
    for candidate in scope.candidates:
        focus = candidate.focuses[0]
        focus.points = [focus.points[0].model_copy(update={'id': f'p{i}'}) for i in range(12)]
    snapshot, points = topic_selection(scope, ['c-http', 'culture'], input_text='综合学习', preparation_id='p', version=1)
    assert len(points) == len({p.id for p in points}) == 12
    assert [len(t.scope_point_ids) for t in snapshot.selected_topics] == [6, 6]
    assert {t.candidate_id for t in snapshot.selected_topics} == {'c-http', 'culture'}
    with pytest.raises(ValueError):
        topic_selection(scope, ['forged'], input_text='综合学习', preparation_id='p', version=1)


@pytest.mark.parametrize('extra', [
    {'candidate_ids': []}, {'candidate_ids': ['c', 'c']},
    {'candidate_ids': ['c'], 'candidate_id': 'old', 'focus_id': 'old', 'scope_point_ids': ['p']},
])
def test_invalid_multiselect_contract(extra):
    with pytest.raises(ValidationError):
        GenerateRequest(preparation_id='p', scope_version=1, **extra)


def test_review_must_cover_every_selected_topic():
    ctx = context()
    ctx['scope']['selected_topics'] = [{'scope_point_ids': ['p1']}, {'scope_point_ids': ['p2']}]
    quiz = QuizDraftResult(status='ready', quiz=quiz_payload()).quiz
    verdict = QuizReview.model_validate(review())
    verdict.covered_point_ids = ['p1']
    assert not review_decision(quiz, verdict, [], ctx)
    verdict.covered_point_ids = ['p1', 'p2']
    assert review_decision(quiz, verdict, [], ctx)


@pytest.mark.anyio
async def test_multiselect_api_generation_and_history_keep_both_topics(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as client:
        await login(client)
        old = await confirmed_body(client)
        with system.state.accounts.database.session() as db:
            row = db.get(TopicPreparation, old['preparation_id'])
            row.content = {**row.content, 'scope': topics().model_dump(mode='json')}
        body = {'preparation_id': old['preparation_id'], 'scope_version': 1,
                'candidate_ids': ['c-http', 'culture'], 'question_count': 3}
        invalid = await client.post('/api/v1/quiz/generate', json={**body, 'candidate_ids': ['forged']})
        assert invalid.status_code == 422
        assert (await client.get('/api/v1/me')).json()['data']['quota']['remaining'] == 10
        response = await client.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'multi'}, json=body)
        assert response.status_code == 200, response.text
        operation = (await client.get('/api/v1/operations/multi')).json()['data']
        assert operation['status'] == 'succeeded', operation
        snapshot = operation['result']['quiz']['learning_scope']
        assert [t['candidate_id'] for t in snapshot['selected_topics']] == ['c-http', 'culture']
        assert len(set(snapshot['scope_point_ids'])) == 2
        history = (await client.get('/api/v1/learning')).json()['data']
        assert history['sessions'][0]['quiz']['learning_scope'] == snapshot
        recovered = await client.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'multi'}, json={**body, 'candidate_ids': ['culture', 'c-http']})
        assert recovered.status_code == 200


@pytest.mark.anyio
async def test_legacy_recovery_digest_unchanged(system):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system), base_url='http://test') as client:
        await login(client)
        body = await confirmed_body(client)
        response = await client.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'legacy'}, json=body)
        assert response.status_code == 200
        # Freeze the pre-extension request shape when checking old recovery keys.
        legacy = GenerateRequest.model_validate(body).model_dump(exclude={'candidate_ids','generate_images'})
        with system.state.accounts.database.session() as db:
            operation = db.scalar(select(Operation).where(Operation.key == 'legacy'))
            assert operation.digest == digest(json.dumps(legacy, ensure_ascii=False, sort_keys=True))
