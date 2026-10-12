from pathlib import Path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", env_file_encoding="utf-8", extra="ignore")
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
    ai_minute_limit: int = Field(3, ge=1)
    report_attempt_limit: int = Field(3, ge=1)
    login_minute_limit: int = Field(30, ge=1)

    @model_validator(mode='after')
    def separate_test_database(self):
        import re
        for name in (self.mysql_database, self.mysql_test_database):
            if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', name):
                raise ValueError('Invalid database name')
        if self.database_testing and (self.mysql_test_database == self.mysql_database or not self.mysql_test_database.endswith('_test')):
            raise ValueError('Tests require a separate database ending in _test')
        return self
