"""Independent image quotas, requests and deletion-safe object ownership."""
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..accounts.database import Base, utcnow


class ImageUsage(Base):
    __tablename__ = 'question_image_usage'
    identity: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)


class ImagePlan(Base):
    __tablename__ = 'question_image_plans'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='started')
    scenes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)


class ImageDispatch(Base):
    __tablename__ = 'question_image_dispatch'
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_allowed_at: Mapped[float] = mapped_column(Float(53))


class ImageCall(Base):
    __tablename__ = 'question_image_calls'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    operation_id: Mapped[str] = mapped_column(String(64))
    question_id: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    day: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16), default='started')
    object_key: Mapped[str] = mapped_column(String(128))
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'operation_id', 'question_id', name='uq_image_call_question'),)


class ImageAsset(Base):
    __tablename__ = 'question_image_assets'
    # No user FK: a reserved key must survive account deletion and late upload.
    object_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    bucket: Mapped[str] = mapped_column(String(128))
    region: Mapped[str] = mapped_column(String(64))
    delete_after: Mapped[object | None] = mapped_column(DateTime, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
