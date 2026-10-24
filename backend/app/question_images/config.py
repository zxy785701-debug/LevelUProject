"""Optional, independently validated settings never prevent core API startup."""
import importlib.util
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from .contracts import permanent_https


class ImageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / '.env',
        env_file_encoding='utf-8', extra='ignore', populate_by_name=True, hide_input_in_errors=True)
    enabled: bool = Field(True, validation_alias='QUIZ_IMAGES_ENABLED')
    api_key: SecretStr = Field(SecretStr(''), validation_alias='IMAGE_API_KEY')
    base_url: str = Field('', validation_alias='IMAGE_BASE_URL')
    embedding_key: SecretStr = Field(SecretStr(''), validation_alias='KNOWLEDGE_EMBEDDING_API_KEY', repr=False)
    embedding_url: str = Field('', validation_alias='KNOWLEDGE_EMBEDDING_BASE_URL', repr=False)
    model: Literal['qwen-image-2.0'] = Field('qwen-image-2.0', validation_alias='IMAGE_MODEL')
    size: Literal['512*512'] = Field('512*512', validation_alias='IMAGE_SIZE')
    daily_limit: int = Field(20, ge=1, le=1000, validation_alias='IMAGE_DAILY_LIMIT')
    concurrency: int = Field(5, ge=1, le=5, validation_alias='IMAGE_CONCURRENCY')
    min_request_interval_seconds: float = Field(.55, ge=0, le=60, validation_alias='IMAGE_MIN_REQUEST_INTERVAL_SECONDS')
    timeout_seconds: float = Field(60, gt=0, le=180, validation_alias='IMAGE_TIMEOUT_SECONDS')
    stage_timeout_seconds: float = Field(90, gt=0, le=180, validation_alias='IMAGE_STAGE_TIMEOUT_SECONDS')
    download_timeout_seconds: float = Field(15, gt=0, le=30, validation_alias='IMAGE_DOWNLOAD_TIMEOUT_SECONDS')
    upload_timeout_seconds: int = Field(15, ge=1, le=30, validation_alias='IMAGE_UPLOAD_TIMEOUT_SECONDS')
    max_bytes: int = Field(8 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024, validation_alias='IMAGE_MAX_BYTES')
    cos_secret_id: SecretStr = Field(SecretStr(''), validation_alias='COS_SECRET_ID')
    cos_secret_key: SecretStr = Field(SecretStr(''), validation_alias='COS_SECRET_KEY')
    cos_region: str = Field('', validation_alias='COS_REGION', pattern=r'^(?:[a-z]+-[a-z]+(?:-[a-z]+)?-?\d*|)$')
    cos_bucket: str = Field('', validation_alias='COS_BUCKET', pattern=r'^(?:[a-z0-9][a-z0-9-]*-\d+|)$')
    public_base_url: str = Field('', validation_alias='COS_PUBLIC_BASE_URL')

    @field_validator('public_base_url')
    @classmethod
    def distribution_url(cls, value):
        return permanent_https(value).rstrip('/') if value else ''

    @model_validator(mode='after')
    def reuse_bailian(self):
        if not self.api_key.get_secret_value().strip():
            self.api_key = self.embedding_key
        if not self.base_url:
            self.base_url = self.embedding_url
        if self.base_url:
            p = urlsplit(self.base_url)
            if (p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment
                    or p.port not in (None,443) or p.path.rstrip('/') != '/api/v1'
                    or not (p.hostname == 'dashscope.aliyuncs.com' or p.hostname.endswith('.cn-beijing.maas.aliyuncs.com'))):
                raise ValueError('请使用北京百炼工作空间的 HTTPS 原生 API 地址（/api/v1）')
            self.base_url = self.base_url.rstrip('/')
        return self

    def unavailable_reason(self, *, check_dependencies=True):
        if not self.enabled:
            return 'IMAGE_DISABLED'
        if not self.api_key.get_secret_value().strip() or not self.base_url:
            return 'IMAGE_NOT_CONFIGURED'
        if not all((self.cos_secret_id.get_secret_value().strip(), self.cos_secret_key.get_secret_value().strip(),
                    self.cos_region, self.cos_bucket, self.public_base_url)):
            return 'COS_NOT_CONFIGURED'
        if check_dependencies and importlib.util.find_spec('qcloud_cos') is None:
            return 'COS_DEPENDENCY_UNAVAILABLE'
        return None


def load_settings(overrides=None):
    try:
        return (ImageSettings() if overrides is None else ImageSettings(_env_file=None, **overrides)), None
    except (ValidationError, OSError, ValueError):
        return None, 'IMAGE_CONFIGURATION_INVALID'
