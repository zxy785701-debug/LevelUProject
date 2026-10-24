"""Stored/server-authored fields, deliberately excluded from AI draft schemas."""
import ipaddress
from typing import Annotated
from urllib.parse import urlsplit
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def permanent_https(value: str) -> str:
    parsed = urlsplit(value)
    if (len(value) > 2048 or parsed.scheme != 'https' or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.port not in (None, 443) or any(c.isspace() for c in value) or '\\' in value
            or parsed.hostname == 'localhost' or parsed.hostname.endswith('.localhost')):
        raise ValueError('图片必须使用长期 HTTPS 分发地址')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return value
    if not address.is_global:
        raise ValueError('图片域名必须可公开访问')
    return value


ImageURL = Annotated[str, AfterValidator(permanent_https)]


class ImageGeneration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requested: int = Field(ge=0, le=100)
    generated: int = Field(ge=0, le=100)
    reason_code: str | None = Field(default=None, max_length=80)

    @model_validator(mode='after')
    def counts(self):
        if self.generated > self.requested:
            raise ValueError('配图数量超出题量')
        return self
