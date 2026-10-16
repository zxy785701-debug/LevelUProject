from copy import deepcopy
import json

def quiz_payload(count=3):
    types = ["single", "multi", "judge"] if count == 3 else ["single", "single", "single", "multi", "judge"]
    return {"title":"HTTP 基础", "summary":"理解请求与会话", "questions":[{
        "id":f"q{i}","type":kind,"stem":f"第 {i+1} 个问题？",
        "options":[{"id":"A","text":"正确"},{"id":"B","text":"错误"}] if kind == "judge" else [{"id":c,"text":f"选项 {c}"} for c in "ABCD"],
        "answers":["A","B"] if kind == "multi" else ["A"],
        "explanation":"说明原因与关键概念。", "knowledge_point":"请求与会话"
    } for i, kind in enumerate(types)]}

REPORT = {"summary":["已经迈出第一步。","注意概念之间的区别。","继续用例子练习。"],"mastered_points":["请求"],"weak_points":["会话"],"suggestions":["用自己的话解释一次。"],"share_quote":"每个问题，都是理解的起点。"}


def grounding_payload(schema, prompt, quiz=None):
    """Deterministic schema responses, never used by production or live evaluation."""
    if schema.__name__ == 'ScopeContent':
        return {'candidates': [{'id': 'c-http', 'topic': 'HTTP', 'domain': '网络协议', 'description': '请求与会话',
                'focuses': [{'id': 'f-http', 'name': '基础概念', 'description': '请求与会话',
                            'points': [{'id': 'p-http', 'name': '请求与会话', 'evidence_status': 'unverified', 'evidence_ids': []}]}]}]}
    if schema.__name__ == 'QuizDraftResult':
        return {'status': 'ready', 'quiz': quiz or quiz_payload(5 if '出 5 道' in prompt else 3)}
    if schema.__name__ == 'QuizReview':
        data = json.loads(prompt.rsplit('Human: ', 1)[-1])
        ids = [s['id'] for s in data['evidence']]
        return {'questions': [{'question_id': q['id'], 'status': 'supported' if ids else 'unsupported',
                               'source_ids': ids[:1], 'reason': '测试审核响应'} for q in data['quiz']['questions']],
                'focus_covered': True, 'covered_point_ids': data['confirmed_scope'].get('scope_point_ids', []), 'reason': '测试范围响应'}
    return None

class FakeGateway:
    def __init__(self, result): self.result, self.calls = result, []
    async def generate(self, schema, prompt, check=None):
        self.calls.append(prompt)
        generated = grounding_payload(schema, prompt, deepcopy(self.result) if schema.__name__ == 'QuizDraftResult' else None)
        result = schema.model_validate(generated if generated is not None else deepcopy(self.result))
        if check: check(result)
        return result
