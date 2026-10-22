"""Public knowledge DTOs are separate from stored records and legacy sessions."""
from datetime import datetime
from typing import Literal
from pydantic import Field,model_validator
from ..models import StrictModel


class DocumentDTO(StrictModel):
    id: str
    title: str
    source_type: Literal['pdf', 'docx', 'txt', 'md', 'markdown', 'web']
    source: dict
    status: Literal['processing', 'ready', 'failed', 'cancelled', 'deleted']
    active_revision_id: str | None = None
    version: int | None = None
    text_chars: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    job_id: str | None = None
    error_code: str | None = None
    message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentPage(StrictModel):
    items: list[DocumentDTO]
    total: int = Field(ge=0)
    page: int = Field(ge=1, le=10000)
    page_size: int = Field(ge=1, le=100)


class ChunkDTO(StrictModel):
    id: str
    revision_id: str
    position: int = Field(ge=0)
    text: str
    location: dict


class ChunkPage(StrictModel):
    items: list[ChunkDTO]
    total: int = Field(ge=0)
    page: int = Field(ge=1, le=10000)
    page_size: int = Field(ge=1, le=100)


class WebImport(StrictModel):
    url: str = Field(min_length=1, max_length=2048)


class MaterialImport(StrictModel):
    material_id: str = Field(min_length=1, max_length=36)


class JobDTO(StrictModel):
    kind: Literal['knowledge_job'] = 'knowledge_job'
    id: str
    job_id: str
    job_type: Literal['import', 'reindex', 'question', 'prepare', 'quiz', 'cleanup']
    document_id: str | None = None
    status: Literal['queued', 'running', 'succeeded', 'failed', 'cancelled']
    stage: str
    progress: int = Field(ge=0, le=100)
    error_code: str | None = None
    message: str | None = None
    retry_after_seconds: int = Field(ge=0)
    deadline: datetime
    created_at: datetime
    result: dict | None = None


class DocumentSelection(StrictModel):
    document_ids: list[str] = Field(default_factory=list,max_length=100)
    all_ready: bool = Field(default=False,strict=True)
    supplement: bool = Field(default=True,strict=True)

    @model_validator(mode='after')
    def explicit_scope(self):
        if (bool(self.document_ids) == self.all_ready or len(set(self.document_ids)) != len(self.document_ids)
                or any(not did or len(did)>36 for did in self.document_ids)):
            raise ValueError('请选择明确资料或全部就绪资料')
        return self


class QuestionRequest(DocumentSelection):
    question: str = Field(min_length=1,max_length=6000)


class ScopeRequest(DocumentSelection):
    goal: str = Field(min_length=1,max_length=6000)


class QuizRequest(StrictModel):
    scope_id: str = Field(min_length=1,max_length=36)
    scope_version: int = Field(ge=1,strict=True)
    candidate_ids: list[str] = Field(min_length=1,max_length=5)
    question_count: Literal[3,5] = 5
    difficulty: Literal['easy','medium'] = 'easy'
    supplement: bool = Field(default=True,strict=True)

    @model_validator(mode='after')
    def unique_topics(self):
        if len(set(self.candidate_ids)) != len(self.candidate_ids): raise ValueError('主题不可重复')
        return self


class QuestionDetail(StrictModel):
    kind: Literal['knowledge_answer']
    id: str
    question: str
    documents: list[dict]
    supplement: bool
    created_at: datetime
    status: Literal['answered','insufficient']
    paragraphs: list[dict]
    sources: list[dict]
    grounding: dict | None
    conflicts: list[dict]
    reason_code: str | None
    message: str | None
    network: dict
