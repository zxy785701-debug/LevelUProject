import httpx
import pytest
from app.config import Settings
from app.main import create_app
from app.models import Quiz, ReportRequest
from app.scoring import score
from tests.helpers import FakeGateway, REPORT, quiz_payload

def request_payload(count=3, mode="new"):
    q={**quiz_payload(count),"id":"quiz1","created_at":"2026-10-12T00:00:00Z","source_text":"HTTP 基础","difficulty":"easy"}
    return {"quiz":q,"answers":[{"question_id":x["id"],"selected":x["answers"],"elapsed_ms":1000} for x in q["questions"]],"mode":mode}

@pytest.mark.parametrize("count",[3,5])
def test_all_correct(count):
    s=score(ReportRequest.model_validate(request_payload(count)))
    assert s["correct_count"]==count and s["accuracy"]==100
    assert s["xp"]==count*10 and s["coins"]==count*2 and s["duration_ms"]==count*1000
    assert s["knowledge_points"][0]["correct"]==count

def test_answer_sets_and_no_credit_for_partial():
    p=request_payload(); p["answers"][1]["selected"]=["B","A"]
    assert score(ReportRequest.model_validate(p))["correct_count"]==3
    p["answers"][1]["selected"]=["A"]
    assert score(ReportRequest.model_validate(p))["correct_count"]==2
    p["answers"][1]["selected"]=["A","B","C"]
    assert score(ReportRequest.model_validate(p))["correct_count"]==2

@pytest.mark.parametrize("mode",["review","replay"])
def test_no_repeat_reward(mode):
    s=score(ReportRequest.model_validate(request_payload(mode=mode)))
    assert s["xp"]==0 and s["coins"]==0

def test_all_incorrect():
    p=request_payload()
    for a in p["answers"]: a["selected"]=["B"]
    s=score(ReportRequest.model_validate(p))
    assert s["correct_count"]==0 and s["xp"]==0

@pytest.mark.parametrize("bad",["duplicate","missing","unknown","illegal","double","elapsed","cheat"])
def test_invalid_answers(bad):
    p=request_payload()
    if bad=="duplicate": p["answers"].append(p["answers"][0])
    if bad=="missing": p["answers"].pop()
    if bad=="unknown": p["answers"][0]["question_id"]="other"
    if bad=="illegal": p["answers"][0]["selected"]=["Z"]
    if bad=="double": p["answers"][0]["selected"]=["A","A"]
    if bad=="elapsed": p["answers"][0]["elapsed_ms"]=-1
    if bad=="cheat": p["answers"][0]["is_correct"]=True
    with pytest.raises(ValueError): ReportRequest.model_validate(p)

@pytest.mark.anyio
async def test_report_recomputes_stats():
    g=FakeGateway(REPORT)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Settings(_env_file=None),g)),base_url="http://test") as c:
        r=await c.post("/api/v1/report/generate",json=request_payload())
    assert r.status_code==200
    d=r.json()["data"]
    assert d["stats"]["accuracy"]==100 and d["share_quote"]==REPORT["share_quote"]
    assert len(d["summary"])==3 and "100" in g.calls[0]
