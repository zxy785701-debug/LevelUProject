from pathlib import Path
from types import SimpleNamespace
import pytest


def test_storage_and_database_must_be_explicitly_isolated(tmp_path):
    from tests.knowledge_support import assert_test_boundary
    settings = SimpleNamespace(database_testing=True, mysql_database='levelup', mysql_test_database='levelup_test')
    assert_test_boundary(settings, 'levelup_test', tmp_path / 'index', tmp_path)
    for database in ('levelup', 'other_test', ''):
        with pytest.raises(RuntimeError):
            assert_test_boundary(settings, database, tmp_path / 'index', tmp_path)
    with pytest.raises(RuntimeError):
        assert_test_boundary(settings, 'levelup_test', tmp_path.parent / 'private-user-index', tmp_path)
    settings.database_testing = False
    with pytest.raises(RuntimeError):
        assert_test_boundary(settings, 'levelup_test', tmp_path / 'index', tmp_path)


def test_test_guard_rejects_temp_directory_itself_and_symlinks(tmp_path):
    from tests.knowledge_support import assert_test_boundary
    settings = SimpleNamespace(database_testing=True, mysql_database='levelup', mysql_test_database='levelup_test')
    with pytest.raises(RuntimeError):
        assert_test_boundary(settings, 'levelup_test', tmp_path, tmp_path)
    with pytest.raises(RuntimeError):
        assert_test_boundary(settings, 'levelup_test', Path('relative'), tmp_path)


def test_real_mysql_identity_is_checked_before_test_cleanup():
    from app.config import Settings
    from app.accounts.database import Database
    from tests.knowledge_support import assert_database
    database = Database(Settings(database_testing=True))
    try:
        with database.engine.connect() as connection:
            assert_database(database.settings, connection)
    finally:
        database.engine.dispose()
