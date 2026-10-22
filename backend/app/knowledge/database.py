"""MySQL owns permissions, immutable content versions and durable operation state."""
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..accounts.database import Base, utcnow


class Document(Base):
    __tablename__ = 'knowledge_documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    source_type: Mapped[str] = mapped_column(String(16))
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default='processing')
    active_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    deleted_at: Mapped[object | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[object] = mapped_column(DateTime, default=utcnow)


class Revision(Base):
    __tablename__ = 'knowledge_revisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('knowledge_documents.id', ondelete='CASCADE'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    profile: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='staging')
    text: Mapped[str] = mapped_column(Text(16777215), default='')
    segments: Mapped[list] = mapped_column(JSON, default=list)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    parser_version: Mapped[str] = mapped_column(String(64), default='knowledge-parser-v1')
    splitter_version: Mapped[str] = mapped_column(String(64), default='knowledge-splitter-v1')
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint('document_id', 'number', name='uq_knowledge_revision_number'),)


class Chunk(Base):
    __tablename__ = 'knowledge_chunks'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey('knowledge_revisions.id', ondelete='CASCADE'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    location: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('revision_id', 'position', name='uq_knowledge_chunk_position'),)


class Job(Base):
    __tablename__ = 'knowledge_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(128, collation='utf8mb4_bin'))
    digest: Mapped[str] = mapped_column(String(64))
    operation_id: Mapped[str] = mapped_column(String(36), index=True)
    ai_operation_id: Mapped[str | None] = mapped_column(ForeignKey('ai_operations.id', ondelete='SET NULL'), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='queued', index=True)
    stage: Mapped[str] = mapped_column(String(32), default='queued')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(DateTime, nullable=True, index=True)
    deadline_at: Mapped[object] = mapped_column(DateTime)
    retry_after_seconds: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow, index=True)
    __table_args__ = (UniqueConstraint('user_id', 'kind', 'key', name='uq_knowledge_job_key'),)


class Checkpoint(Base):
    __tablename__ = 'knowledge_checkpoints'
    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    content: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[object] = mapped_column(DateTime, default=utcnow)


class Scope(Base):
    __tablename__ = 'knowledge_scopes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    goal: Mapped[str] = mapped_column(Text)
    documents: Mapped[list] = mapped_column(JSON)
    supplement: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[object] = mapped_column(DateTime, index=True)


class Question(Base):
    __tablename__ = 'knowledge_questions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    question: Mapped[str] = mapped_column(Text)
    documents: Mapped[list] = mapped_column(JSON)
    supplement: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON)
    deleted_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow, index=True)


class Cleanup(Base):
    __tablename__ = 'knowledge_cleanup_outbox'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Intentionally no User FK: cleanup must survive deletion of account rows.
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default='queued', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)


class Usage(Base):
    __tablename__ = 'knowledge_usage'
    identity: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    imports: Mapped[int] = mapped_column(Integer, default=0)
    questions: Mapped[int] = mapped_column(Integer, default=0)
    embedding_reserved: Mapped[int] = mapped_column(Integer, default=0)
    embedding_actual: Mapped[int] = mapped_column(Integer, default=0)


class WorkerLease(Base):
    __tablename__ = 'knowledge_worker_leases'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36))
    fence: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[object] = mapped_column(DateTime)
    heartbeat_at: Mapped[object] = mapped_column(DateTime, default=utcnow)


class EmbeddingCache(Base):
    __tablename__ = 'knowledge_embedding_cache'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    profile: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_type: Mapped[str] = mapped_column(String(12), primary_key=True)
    vector: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)


class PublishedResult(Base):
    __tablename__ = 'knowledge_published_results'
    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)
