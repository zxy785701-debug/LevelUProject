import re
import unicodedata
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class GenerateRequest(StrictModel):
    text: str = Field(min_length=1, max_length=6000)
    question_count: Literal[3, 5] = 5
    difficulty: Literal["easy", "medium"] = "easy"

    @field_validator("text", mode="before")
    @classmethod
    def clean(cls, value):
        if not isinstance(value, str):
            raise ValueError("请输入文本")
        value = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()

    @field_validator("question_count", mode="before")
    @classmethod
    def strict_count(cls, value):
        if type(value) is not int:
            raise ValueError("题量仅支持 3 或 5")
        return value

class Option(StrictModel):
    id: Literal["A", "B", "C", "D"]
    text: str = Field(min_length=1, max_length=500)

class Question(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["single", "multi", "judge"]
    stem: str = Field(min_length=1, max_length=1000)
    options: list[Option] = Field(min_length=2, max_length=4)
    answers: list[str] = Field(min_length=1, max_length=4)
    explanation: str = Field(min_length=1, max_length=2000)
    knowledge_point: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def coherent(self):
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids) or len(set(o.text for o in self.options)) != len(ids):
            raise ValueError("选项标识和内容不可重复")
        if ids != list("ABCD"[:len(ids)]):
            raise ValueError("选项按 A 到 D 排列")
        if len(set(self.answers)) != len(self.answers) or not set(self.answers) <= set(ids):
            raise ValueError("答案必须引用唯一的选项")
        if self.type == "multi" and len(self.answers) < 2:
            raise ValueError("多选题至少两个正确选项")
        if self.type != "multi" and len(self.answers) != 1:
            raise ValueError("单选和判断题仅一个答案")
        if self.type == "judge" and len(ids) != 2:
            raise ValueError("判断题仅两个选项")
        if self.type != "judge" and len(ids) != 4:
            raise ValueError("单选和多选题必须有四个选项")
        return self

class QuizContent(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=300)
    questions: list[Question] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def distinct(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("题目 ID 不可重复")
        return self

class Quiz(QuizContent):
    id: str = Field(min_length=1, max_length=64)
    created_at: datetime
    source_text: str = Field(min_length=1, max_length=6000)
    difficulty: Literal["easy", "medium"]

class Answer(StrictModel):
    question_id: str = Field(min_length=1, max_length=64)
    selected: list[str] = Field(min_length=1, max_length=4)
    elapsed_ms: int = Field(ge=0, le=86400000, strict=True)

class ReportRequest(StrictModel):
    quiz: Quiz
    answers: list[Answer] = Field(min_length=3, max_length=5)
    mode: Literal["new", "replay", "review"] = "new"

    @model_validator(mode="after")
    def match(self):
        questions = {q.id:q for q in self.quiz.questions}
        if len(self.answers) != len(questions) or {a.question_id for a in self.answers} != set(questions):
            raise ValueError("必须提供每题且仅一次作答")
        for a in self.answers:
            q = questions[a.question_id]
            if len(set(a.selected)) != len(a.selected) or not set(a.selected) <= {o.id for o in q.options}:
                raise ValueError("非法答案")
            if q.type != "multi" and len(a.selected) != 1:
                raise ValueError("单选或判断题不可多选")
        return self

class ReportContent(StrictModel):
    summary: list[str] = Field(min_length=3, max_length=3)
    mastered_points: list[str] = Field(max_length=10)
    weak_points: list[str] = Field(max_length=10)
    suggestions: list[str] = Field(min_length=1, max_length=5)
    share_quote: str = Field(min_length=1, max_length=100)

    @field_validator("summary", "mastered_points", "weak_points", "suggestions")
    @classmethod
    def nonempty_lines(cls, values):
        if any(not v.strip() or len(v) > 500 for v in values):
            raise ValueError("分析文本不得为空或过长")
        return [v.strip() for v in values]
