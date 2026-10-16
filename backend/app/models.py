import re
import unicodedata
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .quiz_grounding.snapshots import GroundingStatus, Identifier, LearningScopeSnapshot, QuizSource, QuestionOrigin

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class GenerateRequest(StrictModel):
    text: str | None = Field(default=None, min_length=1, max_length=6000)
    material_id: str | None = Field(default=None, min_length=1, max_length=36)
    point_ids: list[str] = Field(default_factory=list, max_length=1000)
    supplement: bool = False
    preparation_id: str | None = Field(default=None, min_length=1, max_length=36)
    scope_version: int | None = Field(default=None, ge=1, strict=True)
    candidate_id: Identifier | None = None
    candidate_ids: list[Identifier] = Field(default_factory=list, max_length=5)
    focus_id: Identifier | None = None
    scope_point_ids: list[Identifier] = Field(default_factory=list, max_length=12)
    execution: Literal["sync", "background"] = "sync"
    question_count: Literal[3, 5] = 5
    difficulty: Literal["easy", "medium"] = "easy"

    @field_validator("text", mode="before")
    @classmethod
    def clean(cls, value):
        if value is None: return value
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

    @model_validator(mode='after')
    def source_required(self):
        if sum(bool(v) for v in (self.text, self.material_id, self.preparation_id)) != 1: raise ValueError('请选择唯一的文本、材料或已确认主题来源')
        if not self.material_id and (self.point_ids or self.supplement): raise ValueError('请先选择材料')
        if len(set(self.point_ids)) != len(self.point_ids): raise ValueError('知识范围不能重复')
        scope_values = (self.scope_version, self.candidate_id, self.focus_id, self.scope_point_ids)
        if self.preparation_id:
            if self.candidate_ids:
                if not self.scope_version or self.candidate_id or self.focus_id or self.scope_point_ids:
                    raise ValueError('多主题确认不能混用旧的方向或知识点选择')
                if len(set(self.candidate_ids)) != len(self.candidate_ids): raise ValueError('学习主题不能重复')
            elif not all(scope_values): raise ValueError('请提供完整的学习范围确认')
            if len(set(self.scope_point_ids)) != len(self.scope_point_ids): raise ValueError('知识范围不能重复')
            self.execution = 'background'
        elif any(scope_values) or self.candidate_ids:
            raise ValueError('请先选择主题准备记录')
        if self.text and self.execution != 'sync': raise ValueError('请先确认学习范围')
        return self

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
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    grounding: GroundingStatus | None = None
    origin: QuestionOrigin | None = None

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

class RewardRate(StrictModel):
    xp: Literal[10, 15]
    coins: Literal[2, 3]

class Quiz(QuizContent):
    id: str = Field(min_length=1, max_length=64)
    created_at: datetime
    source_text: str = Field(min_length=1, max_length=6000)
    difficulty: Literal["easy", "medium"]
    reward: RewardRate | None = None
    source: QuizSource | None = None
    learning_scope: LearningScopeSnapshot | None = None
    grounding: GroundingStatus | None = None

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
