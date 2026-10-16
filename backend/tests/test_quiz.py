from copy import deepcopy
import httpx
import pytest
from pydantic import ValidationError
from app.config import Settings
from app.main import create_app
from app.models import QuizContent, Question
from tests.helpers import FakeGateway, quiz_payload
from tests.test_mysql_accounts import system, login, generate, confirmed_body

@pytest.mark.parametrize("count", [3,5])
@pytest.mark.parametrize("difficulty", ["easy","medium"])
@pytest.mark.anyio
async def test_quiz_contract(count,difficulty,system):
    gateway = FakeGateway(quiz_payload(count))
    system.state.gateway = gateway
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url="http://test") as c:
        await login(c)
        session = await generate(c, count=count, difficulty=difficulty, text='HTTP 基础')
    data=session['quiz']
    assert data["id"] and data["created_at"] and len(data["questions"])==count
    assert data["source_text"]=="HTTP 基础" and data["difficulty"]==difficulty
    assert any('JSON' in prompt and 'HTTP 基础' in prompt for prompt in gateway.calls)

@pytest.mark.parametrize("change", [
    {"answers":["Z"]}, {"answers":["A","A"]}, {"answers":[]},
    {"answers":["A","B"]}, {"explanation":" "}, {"knowledge_point":""},
    {"options":[{"id":"A","text":"a"},{"id":"A","text":"b"}]},
    {"options":[{"id":"A","text":"相同"},{"id":"B","text":"相同"}]},
])
def test_question_invalid(change):
    q=deepcopy(quiz_payload()["questions"][0]); q.update(change)
    with pytest.raises(ValidationError): Question.model_validate(q)

def test_multi_requires_two_and_judge_two_options():
    q=quiz_payload()["questions"][1]; q["answers"]=["A"]
    with pytest.raises(ValidationError): Question.model_validate(q)
    q=quiz_payload()["questions"][2]; q["options"].append({"id":"C","text":"其他"})
    with pytest.raises(ValidationError): Question.model_validate(q)

def test_duplicate_question_id():
    q=quiz_payload(); q["questions"][1]["id"]="q0"
    with pytest.raises(ValidationError): QuizContent.model_validate(q)

@pytest.mark.anyio
async def test_wrong_mix_rejected(system):
    gateway=FakeGateway(quiz_payload(5))
    system.state.gateway = gateway
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=system),base_url="http://test") as c:
        await login(c)
        body = await confirmed_body(c)
        r=await c.post('/api/v1/quiz/generate', headers={'Idempotency-Key': 'wrong-mix'}, json=body)
        assert r.status_code == 200
        result = (await c.get('/api/v1/operations/wrong-mix')).json()['data']
    assert result['status'] == 'failed' and result['error_code'] == 'MODEL_INVALID_OUTPUT'
