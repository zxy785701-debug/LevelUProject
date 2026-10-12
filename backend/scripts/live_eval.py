"""Opt-in real DeepSeek acceptance. Never prints keys or provider response bodies."""
import asyncio
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.llm import ModelGateway
from app.models import GenerateRequest, ReportRequest
from app.services import generate_quiz, generate_report

async def run():
    settings=Settings()
    if not settings.deepseek_api_key.get_secret_value():
        print("Missing local DEEPSEEK_API_KEY; real evaluation not run.")
        return 2
    rows=[]; sample=None
    topics=["HTTP 为什么是无状态的？","什么是复利？","用生活例子理解条件概率","JavaScript 闭包","咖啡为什么会提神？","牛顿第一定律","Python 列表与元组的区别","光合作用的基本过程","二分查找的原理","为什么要定期复习知识？"]
    for i,topic in enumerate(topics):
        gateway=ModelGateway(settings); start=time.monotonic()
        try:
            quiz=await generate_quiz(GenerateRequest(text=topic,question_count=3 if i%2 else 5,difficulty="medium" if i%2 else "easy"),settings,gateway)
            sample=sample or quiz
            row={"index":i+1,"topic":topic,"success":True,"attempts":gateway.last_attempts,"seconds":round(time.monotonic()-start,2)}
        except Exception as e:
            row={"index":i+1,"topic":topic,"success":False,"attempts":gateway.last_attempts,"error_code":getattr(e,"code",type(e).__name__),"seconds":round(time.monotonic()-start,2)}
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    report_ok=False
    if sample:
        payload={"quiz":sample,"answers":[{"question_id":q["id"],"selected":q["answers"],"elapsed_ms":2000} for q in sample["questions"]]}
        try:
            report=await generate_report(ReportRequest.model_validate(payload),settings)
            report_ok=True
            (Path(__file__).resolve().parents[1]/"test-results/live-sample.json").write_text(json.dumps({"quiz":sample,"report":report},ensure_ascii=False,indent=2),encoding="utf-8")
        except Exception as e: print("Report error: "+getattr(e,"code",type(e).__name__),flush=True)
    result={"model":settings.deepseek_model,"thinking":"disabled","runs":rows,"first_attempt_successes":sum(x["success"] and x["attempts"]==1 for x in rows),"successes":sum(x["success"] for x in rows),"report_success":report_ok}
    (Path(__file__).resolve().parents[1]/"test-results/live-eval.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="runs"},ensure_ascii=False),flush=True)
    return 0 if result["first_attempt_successes"]>=8 and report_ok else 1

if __name__=="__main__":sys.exit(asyncio.run(run()))
