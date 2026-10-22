"""Validate optional knowledge settings lazily, independently of core startup."""
import importlib.util
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[2]


class KnowledgeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='KNOWLEDGE_', env_file=BACKEND / '.env', env_file_encoding='utf-8',
        extra='ignore', hide_input_in_errors=True,
    )
    enabled: bool = False
    embedding_api_key: SecretStr = SecretStr('')
    embedding_base_url: str = ''
    embedding_region: Literal['cn-beijing'] = 'cn-beijing'
    embedding_model: Literal['text-embedding-v4'] = 'text-embedding-v4'
    embedding_dimension: Literal[1024] = 1024
    embedding_distance: Literal['cosine'] = 'cosine'
    embedding_batch_size: int = Field(10, ge=1, le=10)
    embedding_timeout_seconds: float = Field(30, gt=0, le=120)
    embedding_max_attempts: int = Field(3, ge=1, le=3)
    embedding_daily_tokens: int = Field(200000, ge=1)
    embedding_concurrency: int = Field(2, ge=1, le=4)
    storage_root: Path = BACKEND / 'knowledge-data'
    max_documents: int = Field(100, ge=1)
    max_total_chars: int = Field(5000000, ge=1)
    import_daily_limit: int = Field(20, ge=1)
    question_daily_limit: int = Field(20, ge=1)
    chunk_size: int = Field(1000, ge=100, le=2000)
    chunk_overlap: int = Field(150, ge=0)
    worker_concurrency: int = Field(2, ge=1, le=2)
    lease_seconds: int = Field(30, ge=15, le=120)
    heartbeat_seconds: int = Field(5, ge=1, le=20)
    queue_timeout_seconds: int = Field(600, ge=30, le=3600)
    job_max_attempts: int = Field(3, ge=1, le=3)
    import_timeout_seconds: int = Field(900, ge=30, le=1800)
    question_timeout_seconds: int = Field(180, ge=30, le=600)
    preparation_timeout_seconds: int = Field(240, ge=30, le=600)
    quiz_timeout_seconds: int = Field(300, ge=30, le=600)

    @field_validator('embedding_dimension',mode='before')
    @classmethod
    def fixed_dimension_from_environment(cls,value):
        # BaseSettings reads Literal[int] dotenv values as strings.
        return 1024 if isinstance(value,str) and value == '1024' else value

    @field_validator('embedding_base_url')
    @classmethod
    def provider_endpoint(cls, value):
        if not value:
            return value
        parts = urlsplit(value)
        host = parts.hostname or ''
        if (parts.scheme != 'https' or parts.username or parts.password or parts.query or parts.fragment
                or parts.port not in (None, 443) or parts.path.rstrip('/') != '/api/v1'
                or not (host.endswith('.cn-beijing.maas.aliyuncs.com') or host == 'dashscope.aliyuncs.com')):
            raise ValueError('Use the Beijing workspace API Host with /api/v1 from the Bailian console')
        return value.rstrip('/')

    @field_validator('storage_root')
    @classmethod
    def absolute_storage(cls, value):
        if not value.is_absolute():
            raise ValueError('Knowledge storage requires an absolute private directory')
        return value

    @model_validator(mode='after')
    def coherent(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('Chunk overlap must be less than chunk size')
        if self.heartbeat_seconds * 2 >= self.lease_seconds:
            raise ValueError('Heartbeat must leave sufficient lease renewal time')
        return self

    def unavailable_reason(self, *, check_dependencies=True):
        if not self.enabled:
            return 'KNOWLEDGE_DISABLED'
        if not self.embedding_api_key.get_secret_value().strip() or not self.embedding_base_url:
            return 'EMBEDDING_NOT_CONFIGURED'
        try:
            parent = self.storage_root
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            if not parent.is_dir() or not os.access(parent, os.W_OK):
                return 'KNOWLEDGE_STORAGE_UNAVAILABLE'
        except OSError:
            return 'KNOWLEDGE_STORAGE_UNAVAILABLE'
        if check_dependencies and any(importlib.util.find_spec(name) is None for name in (
                'chromadb', 'langchain_chroma', 'langchain_text_splitters')):
            return 'KNOWLEDGE_DEPENDENCY_UNAVAILABLE'
        return None


def load_settings():
    """A malformed optional env value disables knowledge, never the core app."""
    try:
        return KnowledgeSettings(), None
    except (ValidationError, OSError):
        return None, 'KNOWLEDGE_CONFIGURATION_INVALID'
