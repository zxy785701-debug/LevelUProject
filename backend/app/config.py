from pathlib import Path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True)
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    model_timeout_seconds: float = Field(30, gt=0, le=120)
    model_max_attempts: int = Field(3, ge=1, le=5)
    cors_origins: list[str] = ["http://localhost:10086", "http://127.0.0.1:10086"]
    mysql_host: str = '127.0.0.1'
    mysql_port: int = Field(3306, ge=1, le=65535)
    mysql_user: str = ''
    mysql_password: SecretStr = SecretStr('')
    mysql_database: str = 'levelup'
    mysql_test_database: str = 'levelup_test'
    database_testing: bool = False
    wechat_app_id: str = ''
    wechat_app_secret: SecretStr = SecretStr('')
    identity_hash_secret: SecretStr = SecretStr('')
    session_days: int = Field(7, ge=1, le=90)
    quiz_daily_limit: int = Field(10, ge=1)
    ai_minute_limit: int = Field(10, ge=1)
    report_attempt_limit: int = Field(3, ge=1)
    login_minute_limit: int = Field(30, ge=1)
    material_max_bytes: int = Field(20 * 1024 * 1024, ge=1)
    material_max_chars: int = Field(100000, ge=1)
    material_max_pages: int = Field(200, ge=1)
    material_daily_limit: int = Field(20, ge=1)
    period_daily_limit: int = Field(5, ge=1)
    source_timeout_seconds: float = Field(30, gt=0, le=60)
    jina_api_key: SecretStr = SecretStr('')
    tavily_api_key: SecretStr = SecretStr('')
    quiz_grounding_enabled: bool = True
    topic_prepare_daily_limit: int = Field(20, ge=1)
    topic_prepare_timeout_seconds: float = Field(240, gt=0, le=600)
    grounded_generation_timeout_seconds: float = Field(300, gt=0, le=600)
    prepare_model_call_limit: int = Field(5, ge=2, le=20)
    generation_model_call_limit: int = Field(7, ge=2, le=20)
    retrieval_model_call_limit: int = Field(3, ge=1, le=10)
    retrieval_tool_call_limit: int = Field(4, ge=1, le=12)
    search_max_results: int = Field(10, ge=1, le=10)
    extract_max_urls_per_call: int = Field(3, ge=1, le=3)
    retrieval_max_page_attempts: int = Field(12, ge=1, le=36)
    tavily_timeout_seconds: float = Field(20, gt=0, le=60)
    tool_result_max_bytes: int = Field(2 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    evidence_max_chars: int = Field(24000, ge=1000, le=100000)
    topic_preparation_ttl_hours: int = Field(24, ge=1, le=168)
    evidence_reuse_seconds: int = Field(1800, ge=0, le=86400)

    @property
    def tavily_available(self) -> bool:
        return bool(self.tavily_api_key.get_secret_value().strip())

    @model_validator(mode='after')
    def grounding_budgets(self):
        if self.prepare_model_call_limit < self.retrieval_model_call_limit + 1:
            raise ValueError('范围准备预算必须为整理范围保留至少一次模型请求')
        if self.generation_model_call_limit < self.retrieval_model_call_limit + 2:
            raise ValueError('生成预算必须为出题与独立审核保留至少两次模型请求')
        if self.tavily_timeout_seconds > min(self.topic_prepare_timeout_seconds, self.grounded_generation_timeout_seconds):
            raise ValueError('工具超时不能超过阶段期限')
        if self.evidence_reuse_seconds > self.topic_preparation_ttl_hours * 3600:
            raise ValueError('证据复用时间不能超过准备有效期')
        return self

    @model_validator(mode='after')
    def separate_test_database(self):
        import re
        for name in (self.mysql_database, self.mysql_test_database):
            if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', name):
                raise ValueError('Invalid database name')
        if self.database_testing and (self.mysql_test_database == self.mysql_database or not self.mysql_test_database.endswith('_test')):
            raise ValueError('Tests require a separate database ending in _test')
        return self
