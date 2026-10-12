from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", env_file_encoding="utf-8", extra="ignore")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    model_timeout_seconds: float = Field(30, gt=0, le=120)
    model_max_attempts: int = Field(3, ge=1, le=5)
    cors_origins: list[str] = ["http://localhost:10086", "http://127.0.0.1:10086"]
