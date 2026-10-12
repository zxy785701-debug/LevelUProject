from .models import ReportRequest
from .rewards import question_reward

def score(body: ReportRequest) -> dict:
    answers = {a.question_id:a for a in body.answers}
    correct = 0
    points = {}
    details = []
    for q in body.quiz.questions:
        a = answers[q.id]
        ok = set(a.selected) == set(q.answers)
        correct += int(ok)
        point = points.setdefault(q.knowledge_point, {"name":q.knowledge_point,"total":0,"correct":0})
        point["total"] += 1
        point["correct"] += int(ok)
        details.append({"question_id":q.id,"is_correct":ok})
    total = len(body.quiz.questions)
    for point in points.values(): point["accuracy"] = round(point["correct"] / point["total"] * 100)
    reward = question_reward(body.quiz.model_dump())
    return {"total":total,"correct_count":correct,"accuracy":round(correct/total*100),
            "duration_ms":sum(a.elapsed_ms for a in body.answers),
            "xp":correct*reward['xp'] if body.mode == "new" else 0,"coins":correct*reward['coins'] if body.mode == "new" else 0,
            "knowledge_points":list(points.values()),"results":details}
