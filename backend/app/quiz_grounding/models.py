"""Validated contracts for retrieval, confirmation, and generation."""
from collections import Counter
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from ..models import GenerateRequest, QuizContent, Quiz, Option
from .snapshots import EvidenceSegment, GroundingModel, GroundingStatus, Identifier, QuestionOrigin
from .countries import COUNTRIES
from ..question_images.contracts import ImageURL


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f"{label}不能重复")


class SearchParameters(GroundingModel):
    query: str = Field(min_length=1, max_length=400)
    content_mode: Literal["summary", "full"] = "summary"
    max_results: int = Field(default=3, ge=1, le=10, strict=True)
    search_depth: Literal["basic", "advanced"] = "basic"
    topic: Literal["general", "news", "finance"] = "general"
    country: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-z ]+$")
    time_range: Literal["day", "week", "month", "year"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def domain_names(cls, values):
        for value in values:
            parsed = urlsplit("https://" + value)
            if not parsed.hostname or parsed.hostname != value or parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError("来源限制必须为域名")
        unique(values, "域名")
        return values

    @model_validator(mode="after")
    def compatible(self):
        if self.country is not None and self.country not in COUNTRIES:
            raise ValueError("国家偏向必须使用 Tavily 支持的 country 值；城市请写入查询")
        if self.country and self.topic != "general":
            raise ValueError("国家偏向仅支持 general 搜索")
        if self.time_range and (self.start_date or self.end_date):
            raise ValueError("相对时间和日期区间不能同时使用")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("日期区间不正确")
        if set(self.include_domains) & set(self.exclude_domains):
            raise ValueError("来源域名不能同时包含和排除")
        return self


class ExtractParameters(GroundingModel):
    urls: list[str] = Field(min_length=1, max_length=3)
    content_mode: Literal["full", "focused"] = "full"
    extract_depth: Literal["basic", "advanced"] = "basic"
    query: str | None = Field(default=None, min_length=1, max_length=400)
    chunks_per_source: int | None = Field(default=None, ge=1, le=5, strict=True)

    @field_validator("urls")
    @classmethod
    def http_urls(cls, values):
        unique(values, "网址")
        for value in values:
            parsed = urlsplit(value)
            if len(value) > 2048 or parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("仅支持不含凭证的公开 HTTP(S) 网址")
        return values

    @model_validator(mode="after")
    def content_selection(self):
        if self.content_mode == "full" and (self.query is not None or self.chunks_per_source is not None):
            raise ValueError("完整页面读取不能指定片段查询或数量")
        if self.content_mode == "focused" and (not self.query or self.chunks_per_source is None):
            raise ValueError("定向提取必须提供查询和片段数量")
        return self


class ToolFailure(GroundingModel):
    url: str | None = Field(default=None, max_length=2048)
    code: str = Field(min_length=1, max_length=80)


class ToolResult(GroundingModel):
    tool: Literal["tavily_search", "tavily_extract"]
    status: Literal["success", "partial", "failed", "budget_exhausted", "cached"]
    evidence: list[EvidenceSegment] = Field(default_factory=list, max_length=1000)
    failures: list[ToolFailure] = Field(default_factory=list, max_length=20)
    reason_code: str | None = Field(default=None, max_length=80)
    retrieved_at: datetime
    elapsed_ms: int = Field(default=0, ge=0)
    truncated: bool = False
    credits: float | None = Field(default=None, ge=0)


class ScopePoint(GroundingModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=100)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    evidence_status: Literal["available", "unverified"] = "unverified"

    @model_validator(mode="after")
    def evidence_present(self):
        unique(self.evidence_ids, "来源")
        if self.evidence_status == "available" and not self.evidence_ids:
            raise ValueError("已取得资料的知识点必须引用真实片段")
        return self


class ScopeFocus(GroundingModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=500)
    points: list[ScopePoint] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def identifiers(self):
        unique([p.id for p in self.points], "知识点")
        return self


class ScopeCandidate(GroundingModel):
    id: Identifier
    topic: str = Field(min_length=1, max_length=180)
    domain: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=500)
    focuses: list[ScopeFocus] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def identifiers(self):
        unique([f.id for f in self.focuses], "学习方向")
        return self


class ScopeContent(GroundingModel):
    candidates: list[ScopeCandidate] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def identifiers(self):
        unique([c.id for c in self.candidates], "候选领域")
        return self

    def selected(self, candidate_id, focus_id, point_ids):
        candidate = next((c for c in self.candidates if c.id == candidate_id), None)
        focus = next((f for f in candidate.focuses if f.id == focus_id), None) if candidate else None
        if not focus or not point_ids or not set(point_ids) <= {p.id for p in focus.points}:
            raise ValueError("所选知识点不属于当前领域和学习方向")
        unique(point_ids, "知识点")
        return candidate, focus, [p for p in focus.points if p.id in point_ids]

    def check_evidence(self, evidence_ids):
        for candidate in self.candidates:
            for focus in candidate.focuses:
                for point in focus.points:
                    if not set(point.evidence_ids) <= set(evidence_ids):
                        raise ValueError("学习范围包含不存在的来源")


class PrepareRequest(GroundingModel):
    text: str = Field(min_length=1, max_length=6000)

    @field_validator("text", mode="before")
    @classmethod
    def clean(cls, value):
        return GenerateRequest.clean(value)


class Preparation(GroundingModel):
    id: str = Field(min_length=1, max_length=36)
    version: int = Field(default=1, ge=1, strict=True)
    input_text: str = Field(min_length=1, max_length=6000)
    status: Literal["running", "ready", "failed", "cancelled", "expired"]
    stage: Literal["planning", "searching", "extracting", "summarizing", "waiting_rate_limit", "ready", "failed", "cancelled", "expired"]
    content: ScopeContent | None = None
    grounding: GroundingStatus | None = None
    evidence: list[EvidenceSegment] = Field(default_factory=list, max_length=1000)
    error_code: str | None = Field(default=None, max_length=80)
    retry_after_seconds: int = Field(default=0, ge=0)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def ready_content(self):
        if self.status == "ready" and (self.content is None or self.grounding is None):
            raise ValueError("就绪准备必须具有范围和来源状态")
        return self


class QuizDraftResult(GroundingModel):
    status: Literal["ready", "insufficient_knowledge"]
    quiz: QuizContent | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def result_matches_status(self):
        if self.status == "ready":
            if self.quiz is None or self.reason is not None:
                raise ValueError("完成草稿必须包含题库")
            count = len(self.quiz.questions)
            mix = {"single": 1, "multi": 1, "judge": 1} if count == 3 else {"single": 3, "multi": 1, "judge": 1}
            if count not in (3, 5) or Counter(q.type for q in self.quiz.questions) != mix:
                raise ValueError("草稿题型和题量不正确")
        elif self.quiz is not None or not self.reason:
            raise ValueError("知识不足应提供原因而非伪造题库")
        return self


class QuestionReview(GroundingModel):
    question_id: Identifier
    status: Literal["supported", "unsupported", "contradicted", "ambiguous", "off_scope"]
    source_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def support_requires_evidence(self):
        unique(self.source_ids, "来源")
        if self.status == "supported" and not self.source_ids:
            raise ValueError("支持结论必须提供片段依据")
        return self


class QuizReview(GroundingModel):
    questions: list[QuestionReview] = Field(min_length=3, max_length=5)
    focus_covered: bool
    covered_point_ids: list[Identifier] = Field(default_factory=list, max_length=12)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def identifiers(self):
        unique([q.question_id for q in self.questions], "审核题目")
        unique(self.covered_point_ids, "覆盖知识点")
        return self


class GenerationOperation(GroundingModel):
    kind: Literal["generation_operation"] = "generation_operation"
    key: str = Field(min_length=1, max_length=128)
    status: Literal["running", "succeeded", "failed"]
    stage: Literal["retrieving", "planning", "searching", "extracting", "generating", "reviewing", "generating_images", "waiting_rate_limit", "succeeded", "failed"]
    retry_after_seconds: int = Field(default=0, ge=0)
    deadline: datetime
    error_code: str | None = Field(default=None, max_length=80)


class PublicQuestion(GroundingModel):
    """Public DTO permits hidden answers without weakening the stored quiz model."""
    id: str = Field(min_length=1, max_length=64)
    type: Literal['single', 'multi', 'judge']
    stem: str = Field(min_length=1, max_length=1000)
    options: list[Option] = Field(min_length=2, max_length=4)
    answers: list[str] = Field(default_factory=list, max_length=4)
    explanation: str = Field(default='', max_length=2000)
    knowledge_point: str = Field(min_length=1, max_length=100)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    grounding: GroundingStatus | None = None
    origin: QuestionOrigin | None = None
    image_url: ImageURL | None = None


class PublicQuiz(Quiz):
    questions: list[PublicQuestion] = Field(min_length=3, max_length=5)


class SessionResult(GroundingModel):
    id: str
    quiz: PublicQuiz
    mode: Literal['new', 'replay', 'review']
    answers: list[dict]
    cursor: int
    pending_ms: int
    started_at: datetime
    completed_at: datetime | None
    report: dict | None
    review_keys: list[str]


class GenerateEnvelope(GroundingModel):
    code: Literal[0] = 0
    message: str = 'ok'
    data: GenerationOperation | SessionResult
