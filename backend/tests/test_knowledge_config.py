"""Optional knowledge configuration must never prevent the core app starting."""
from pathlib import Path
import importlib
import httpx
import pytest
from pydantic import SecretStr, ValidationError


def config(**values):
    from app.knowledge.config import KnowledgeSettings
    return KnowledgeSettings(_env_file=None, **values)


def test_fixed_dimension_loads_from_dotenv_string_without_loosening_profile(tmp_path):
    from app.knowledge.config import KnowledgeSettings
    env = tmp_path/'knowledge.env'
    env.write_text('KNOWLEDGE_EMBEDDING_DIMENSION=1024\n',encoding='utf-8')
    assert KnowledgeSettings(_env_file=env).embedding_dimension == 1024
    for invalid in ('768','1024.0','true',True):
        with pytest.raises(ValidationError): config(embedding_dimension=invalid)


def test_disabled_without_credentials_and_secrets_are_hidden(tmp_path):
    value = config()
    assert value.enabled is False
    assert value.unavailable_reason() == 'KNOWLEDGE_DISABLED'
    value = config(enabled=True, embedding_api_key='secret-sentinel', embedding_base_url='https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1', storage_root=tmp_path)
    assert 'secret-sentinel' not in repr(value)
    assert value.embedding_model == 'text-embedding-v4'
    assert value.embedding_dimension == 1024
    assert value.embedding_distance == 'cosine'
    assert value.unavailable_reason(check_dependencies=False) is None


def test_invalid_directory_and_missing_key_disable_only_knowledge(tmp_path):
    value = config(enabled=True, storage_root=tmp_path)
    assert value.unavailable_reason(check_dependencies=False) == 'EMBEDDING_NOT_CONFIGURED'
    file = tmp_path / 'file'
    file.write_text('not a directory')
    value = config(enabled=True, embedding_api_key='test', embedding_base_url='https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1', storage_root=file)
    assert value.unavailable_reason(check_dependencies=False) == 'KNOWLEDGE_STORAGE_UNAVAILABLE'
    assert not (tmp_path / 'chroma').exists()


@pytest.mark.parametrize('values', [
    {'embedding_dimension': 768}, {'embedding_model': 'other'}, {'embedding_distance': 'l2'},
    {'embedding_base_url': 'http://localhost:9000'}, {'worker_concurrency': 3},
    {'chunk_overlap': 1000}, {'embedding_batch_size': 11},
])
def test_invalid_config_is_rejected_without_printing_credentials(values):
    with pytest.raises(ValidationError) as error:
        config(embedding_api_key='secret-sentinel', **values)
    assert 'secret-sentinel' not in str(error.value)


def test_optional_dependencies_are_probed_without_import_or_initialization(monkeypatch, tmp_path):
    value = config(enabled=True, embedding_api_key='test', embedding_base_url='https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1', storage_root=tmp_path)
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: None)
    assert value.unavailable_reason() == 'KNOWLEDGE_DEPENDENCY_UNAVAILABLE'
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_bad_optional_configuration_does_not_break_health(monkeypatch):
    from app.config import Settings
    from app.main import create_app
    monkeypatch.setenv('KNOWLEDGE_EMBEDDING_DIMENSION', 'invalid')
    app = create_app(Settings(_env_file=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/v1/health')).json()['data']['status'] == 'ok'
