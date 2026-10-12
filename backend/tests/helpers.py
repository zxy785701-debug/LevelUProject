from copy import deepcopy

def quiz_payload(count=3):
    types = ["single", "multi", "judge"] if count == 3 else ["single", "single", "single", "multi", "judge"]
    return {"title":"HTTP 基础", "summary":"理解请求与会话", "questions":[{
        "id":f"q{i}","type":kind,"stem":f"第 {i+1} 个问题？",
        "options":[{"id":"A","text":"正确"},{"id":"B","text":"错误"}] if kind == "judge" else [{"id":c,"text":f"选项 {c}"} for c in "ABCD"],
        "answers":["A","B"] if kind == "multi" else ["A"],
        "explanation":"说明原因与关键概念。", "knowledge_point":"请求与会话"
    } for i, kind in enumerate(types)]}

REPORT = {"summary":["已经迈出第一步。","注意概念之间的区别。","继续用例子练习。"],"mastered_points":["请求"],"weak_points":["会话"],"suggestions":["用自己的话解释一次。"],"share_quote":"每个问题，都是理解的起点。"}

class FakeGateway:
    def __init__(self, result): self.result, self.calls = result, []
    async def generate(self, schema, prompt, check=None):
        self.calls.append(prompt)
        result = schema.model_validate(deepcopy(self.result))
        if check: check(result)
        return result
