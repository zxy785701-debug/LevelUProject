import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_budgets_and_missing_search_credentials(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    config = Settings(_env_file=None)
    assert not config.tavily_available
    assert config.prepare_model_call_limit == 5 and config.generation_model_call_limit == 7
    assert config.retrieval_model_call_limit == 3 and config.retrieval_tool_call_limit == 4
    assert config.topic_prepare_timeout_seconds == 240 and config.grounded_generation_timeout_seconds == 300
    assert config.ai_minute_limit == 10 and config.quiz_daily_limit == 10


@pytest.mark.parametrize("changes", [
    {"prepare_model_call_limit": 3}, {"generation_model_call_limit": 4},
    {"retrieval_model_call_limit": 5}, {"retrieval_tool_call_limit": 0},
    {"search_max_results": 11}, {"extract_max_urls_per_call": 4},
    {"retrieval_max_page_attempts": 0}, {"topic_prepare_timeout_seconds": 0},
    {"grounded_generation_timeout_seconds": 0}, {"tavily_timeout_seconds": 0},
    {"topic_prepare_timeout_seconds": 10}, {"tool_result_max_bytes": 0},
    {"evidence_max_chars": 0}, {"topic_prepare_daily_limit": 0},
    {"topic_preparation_ttl_hours": 1, "evidence_reuse_seconds": 3601},
])
def test_invalid_budgets_are_rejected(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **changes)


def test_backend_credentials_are_masked_even_on_config_failure():
    secret = "private-tavily-test-secret"
    config = Settings(_env_file=None, tavily_api_key=secret)
    assert config.tavily_available
    assert secret not in repr(config) and secret not in config.model_dump_json()
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, tavily_api_key=secret, generation_model_call_limit=2)
    assert secret not in str(error.value)


def test_feature_switch_can_disable_new_generation_and_limits_are_configurable():
    config = Settings(_env_file=None, quiz_grounding_enabled=False, retrieval_model_call_limit=1, prepare_model_call_limit=2, generation_model_call_limit=3, search_max_results=5, extract_max_urls_per_call=1)
    assert not config.quiz_grounding_enabled
    assert config.generation_model_call_limit == 3 and config.search_max_results == 5
