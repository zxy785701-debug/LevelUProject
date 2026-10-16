"""Strict, backward-compatible provenance stored with a quiz."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class GroundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GroundingStatus(GroundingModel):
    status: Literal["source_backed", "unverified", "material_only"]
    reason_code: str | None = Field(default=None, max_length=80)
    retrieved_at: datetime | None = None
    provider: Literal["tavily"] | None = None
    check_version: str = Field(default="evidence-review-v1", min_length=1, max_length=80)


class EvidenceSegment(GroundingModel):
    id: Identifier
    text: str = Field(min_length=1, max_length=100000)
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    original_url: str | None = Field(default=None, max_length=2048)
    page: int | None = Field(default=None, ge=1)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    supplement: bool = False
    content_kind: Literal["snippet", "full_extract", "focused_extract", "material"] = "material"
    retrieved_at: datetime | None = None
    published_at: str | None = Field(default=None, max_length=100)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    acquisition_status: Literal["available", "partial", "unknown"] = "unknown"
    truncated: bool = False
    context_truncated: bool = False
    source_chars: int | None = Field(default=None, ge=0)
    original_id: Identifier | None = None
    original_quiz_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def range_valid(self):
        if self.end is not None and self.start is not None and self.end < self.start:
            raise ValueError("片段结束时间不能早于开始时间")
        if self.content_kind != "material" and (not self.url or self.retrieved_at is None):
            raise ValueError("网络片段必须记录网址与实际取得时间")
        return self


class QuizSource(GroundingModel):
    type: Literal["topic", "pdf", "docx", "txt", "web", "video", "review"]
    title: str = Field(min_length=1, max_length=500)
    material_id: str | None = Field(default=None, min_length=1, max_length=36)
    url: str | None = Field(default=None, max_length=2048)
    segments: list[EvidenceSegment] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def identifiers(self):
        if len({s.id for s in self.segments}) != len(self.segments):
            raise ValueError("来源片段标识不能重复")
        if self.type == "topic" and self.material_id:
            raise ValueError("主题来源不能伪造材料标识")
        return self


class SelectedTopic(GroundingModel):
    candidate_id: Identifier
    topic: str = Field(min_length=1, max_length=180)
    domain: str = Field(min_length=1, max_length=180)
    scope_point_ids: list[Identifier] = Field(min_length=1, max_length=12)


class LearningScopeSnapshot(GroundingModel):
    input_text: str = Field(min_length=1, max_length=6000)
    topic: str = Field(min_length=1, max_length=180)
    domain: str = Field(min_length=1, max_length=180)
    focus: str = Field(min_length=1, max_length=180)
    points: list[str] = Field(min_length=1, max_length=12)
    preparation_id: str | None = Field(default=None, min_length=1, max_length=36)
    scope_version: int | None = Field(default=None, ge=1, strict=True)
    candidate_id: Identifier | None = None
    focus_id: Identifier | None = None
    scope_point_ids: list[Identifier] = Field(default_factory=list, max_length=12)
    selected_topics: list[SelectedTopic] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def confirmation_complete(self):
        if self.preparation_id and (not self.scope_version or not self.scope_point_ids or not (self.selected_topics or self.candidate_id and self.focus_id)):
            raise ValueError("主题学习范围必须保留完整确认信息")
        if self.selected_topics:
            ids = [p for topic in self.selected_topics for p in topic.scope_point_ids]
            if len({t.candidate_id for t in self.selected_topics}) != len(self.selected_topics) or len(set(ids)) != len(ids) or set(ids) != set(self.scope_point_ids):
                raise ValueError('多主题确认信息与知识点不一致')
        if any(not p.strip() or len(p) > 100 for p in self.points):
            raise ValueError("知识点不能为空或过长")
        return self


class QuestionOrigin(GroundingModel):
    quiz_id: str = Field(min_length=1, max_length=64)
    question_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=80)
    learning_scope: LearningScopeSnapshot | None = None
