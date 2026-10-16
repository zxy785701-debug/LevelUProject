"""Sequential MySQL tests. Schema reset is guarded to the dedicated test DB."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.accounts.database import Base, Database, Operation, Quota, TopicPreparation, User, utcnow
from app.accounts.repository import Accounts
from app.config import Settings


@pytest.fixture
def db():
    settings = Settings(database_testing=True, wechat_app_id='grounding-test',
                        identity_hash_secret='grounding-test-secret-' * 3)
    database = Database(settings)
    with database.engine.connect() as connection:
        actual = connection.scalar(text('SELECT DATABASE()'))
        assert settings.database_testing and actual == settings.mysql_test_database
        assert actual != settings.mysql_database and actual.endswith('_test')
    database.migrate()
    with database.engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(delete(table))
    yield database
    database.engine.dispose()


def reset_schema(db):
    with db.engine.begin() as connection:
        actual = connection.scalar(text('SELECT DATABASE()'))
        assert db.settings.database_testing and actual == db.settings.mysql_test_database
        assert actual != db.settings.mysql_database and actual.endswith('_test')
        metadata = MetaData()
        metadata.reflect(connection)
        assert set(metadata.tables) <= set(Base.metadata.tables) | {'alembic_version'}
        metadata.drop_all(connection)


def upgrade(db, revision):
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with db.engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, revision)


def test_empty_database_and_existing_003_upgrade(db):
    reset_schema(db)
    try:
        upgrade(db, '003_materials_analytics')
        # Reflect the old schema so new ORM columns cannot conceal an upgrade failure.
        old = MetaData()
        old.reflect(db.engine)
        with db.engine.begin() as connection:
            connection.execute(old.tables['users'].insert().values(
                id='old-user', identity='old-identity', appid='old-app', openid='old-openid',
                nickname='已有用户', xp=42, coins=12, avatar_version=0,
                agreement_version='old', consent_at=utcnow(), created_at=utcnow()))
            connection.execute(old.tables['ai_quotas'].insert().values(
                identity='old-identity', day='2026-10-14', quiz_count=4,
                material_count=3, period_count=2, calls=[], busy_until=0))
            connection.execute(old.tables['ai_operations'].insert().values(
                id='old-op', user_id='old-user', key='old-key', digest='a' * 64,
                kind='quiz', status='succeeded', charged=1,
                result={'id': 'original-session'}, created_at=utcnow()))
            connection.execute(old.tables['materials'].insert().values(
                id='old-material', user_id='old-user', content={'title': '旧材料'},
                referenced=1, created_at=utcnow()))
        db.migrate()
        db.migrate()  # Startup can safely run the same migration again.
        with db.session() as s:
            quota = s.get(Quota, 'old-identity')
            assert (quota.quiz_count, quota.material_count, quota.period_count, quota.topic_prepare_count) == (4, 3, 2, 0)
            operation = s.get(Operation, 'old-op')
            assert operation.result == {'id': 'original-session'}
            assert operation.stage is None and operation.deadline_at is None
            assert operation.model_calls == operation.tool_calls == operation.page_attempts == 0
            assert s.get(User, 'old-user').xp == 42
            assert s.execute(text('SELECT content FROM materials WHERE id = :id'), {'id': 'old-material'}).scalar()
        assert 'topic_preparations' in inspect(db.engine).get_table_names()
        reset_schema(db)
        db.migrate()  # Empty database goes through the entire migration chain.
        assert set(Base.metadata.tables) <= set(inspect(db.engine).get_table_names())
    finally:
        db.migrate()


def make_preparation(db, uid, key='same-key', operation_id=None):
    with db.session() as s:
        oid = operation_id or str(uuid4())
        if operation_id is None:
            s.add(Operation(id=oid, user_id=uid, key=str(uuid4()), digest='a' * 64,
                            kind='prepare', stage='planning', deadline_at=utcnow() + timedelta(seconds=240)))
            s.flush()
        prep = TopicPreparation(id=str(uuid4()), user_id=uid, operation_id=oid,
                                key=key, digest='b' * 64, input_text='花少2', version=1,
                                content={'evidence': [{'text': '待清理的真实资料'}]},
                                expires_at=utcnow() + timedelta(hours=24))
        s.add(prep)
        s.flush()
        return prep.id, oid


def test_preparation_unique_keys_account_cascade_and_late_write(db):
    accounts = Accounts(db.settings, db)
    uid = accounts.login({'openid': 'alice'}, 'test')['user']['id']
    other = accounts.login({'openid': 'bob'}, 'test')['user']['id']
    pid, oid = make_preparation(db, uid)
    with pytest.raises(IntegrityError):
        make_preparation(db, uid)
    with pytest.raises(IntegrityError):
        make_preparation(db, uid, key='different-key', operation_id=oid)
    other_pid, _ = make_preparation(db, other)
    accounts.delete_account(uid, {'openid': 'alice'})
    with db.session() as s:
        assert s.get(TopicPreparation, pid) is None
        assert s.get(Operation, oid) is None
        assert s.get(TopicPreparation, other_pid) is not None
    with pytest.raises(IntegrityError):
        make_preparation(db, uid, key='late-result')


def test_prepare_quota_survives_reregistration_and_resets_at_shanghai_midnight(db):
    now = [datetime(2026, 10, 14, 15, 59, 30, tzinfo=timezone.utc).timestamp()]
    accounts = Accounts(db.settings, db, clock=lambda: now[0])
    uid = accounts.login({'openid': 'alice'}, 'test')['user']['id']
    identity = accounts.fingerprint(db.settings.wechat_app_id + ':alice')
    with db.session() as s:
        q = s.get(Quota, identity)
        q.topic_prepare_count, q.quiz_count = 20, 4
    accounts.delete_account(uid, {'openid': 'alice'})
    accounts.cleanup()
    second = accounts.login({'openid': 'alice'}, 'test')['user']['id']
    assert second != uid
    with db.session() as s:
        q = s.get(Quota, identity)
        assert q.topic_prepare_count == 20 and q.quiz_count == 4
        assert q.retire_after is None
    now[0] += 31
    accounts.me(second)
    with db.session() as s:
        q = s.get(Quota, identity)
        assert q.topic_prepare_count == q.quiz_count == 0
        assert q.day == '2026-10-15'
