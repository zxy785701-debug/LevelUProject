"""Real MySQL migrations and constraints, guarded before touching the schema."""
import importlib
from uuid import uuid4
import pytest
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from app.config import Settings
from app.accounts.database import Database, Base, User, utcnow
from tests.knowledge_support import assert_database


@pytest.fixture
def db():
    from app.knowledge import database as models
    value = Database(Settings(database_testing=True))
    with value.engine.connect() as connection:
        assert_database(value.settings, connection)
    value.migrate()
    with value.engine.begin() as connection:
        assert_database(value.settings, connection)
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(delete(table))
    yield value
    value.engine.dispose()


def user(s, uid='knowledge-user'):
    row = User(id=uid, identity=uid, appid='knowledge-test', openid=uid,
               agreement_version='2026-10-12')
    s.add(row)
    s.flush()
    return row


def test_incremental_schema_and_no_core_rewrite(db):
    from app.knowledge.database import Document, Revision, Chunk, Job, Checkpoint, Scope, Question, Cleanup, Usage, WorkerLease, EmbeddingCache, PublishedResult
    tables = set(inspect(db.engine).get_table_names())
    assert {m.__tablename__ for m in (Document, Revision, Chunk, Job, Checkpoint, Scope, Question, Cleanup, Usage, WorkerLease, EmbeddingCache, PublishedResult)} <= tables
    with db.session() as s:
        u = user(s)
        u.xp, u.coins = 55, 11
    db.migrate()
    with db.session() as s:
        assert (s.get(User, 'knowledge-user').xp, s.get(User, 'knowledge-user').coins) == (55, 11)


def test_revision_chunk_and_job_keys_are_unique(db):
    from app.knowledge.database import Document, Revision, Chunk, Job
    with db.session() as s:
        u = user(s)
        s.add(Document(id='doc', user_id=u.id, title='Notes', source_type='md'))
        s.flush()
        s.add(Revision(id='r1', document_id='doc', number=1, profile='profile'))
        s.flush()
        s.add(Chunk(id='chunk1', revision_id='r1', position=0, text='Original text', content_hash='a'*64, location={}))
        s.add(Job(id='job', user_id=u.id, kind='import', key='same', digest='a'*64, operation_id='operation', deadline_at=utcnow()))
    for duplicate in (
        Revision(id='r2', document_id='doc', number=1, profile='profile'),
        Chunk(id='chunk2', revision_id='r1', position=0, text='Other', content_hash='b'*64, location={}),
        Job(id='job2', user_id='knowledge-user', kind='import', key='same', digest='b'*64, operation_id='other', deadline_at=utcnow()),
    ):
        with pytest.raises(IntegrityError), db.session() as s:
            s.add(duplicate)
            s.flush()


def test_account_cascade_preserves_independent_cleanup_and_identity_usage(db):
    from app.knowledge.database import Document, Revision, Chunk, Job, Cleanup, Usage
    with db.session() as s:
        u = user(s)
        s.add(Document(id='doc', user_id=u.id, title='Notes', source_type='txt'))
        s.flush()
        s.add(Revision(id='rev', document_id='doc', number=1, profile='profile'))
        s.flush()
        s.add(Chunk(id='chunk', revision_id='rev', position=0, text='Text', content_hash='a'*64, location={}))
        s.add(Cleanup(id='cleanup', user_id=u.id, payload={'account_id': u.id}))
        s.add(Usage(identity=u.identity, day='2026-10-18'))
    with db.session() as s:
        s.delete(s.get(User, 'knowledge-user'))
    with db.session() as s:
        assert s.get(Document, 'doc') is None and s.get(Chunk, 'chunk') is None
        assert s.get(Cleanup, 'cleanup') is not None
        assert s.get(Usage, ('knowledge-user', '2026-10-18')) is not None


def test_empty_knowledge_downgrade_is_safe_but_nonempty_is_refused(db):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from app.knowledge.database import Document
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with db.engine.begin() as connection:
        assert_database(db.settings, connection)
        config.attributes['connection'] = connection
        command.downgrade(config, '006_retrieval_audit')
    assert 'knowledge_documents' not in inspect(db.engine).get_table_names()
    db.migrate()
    with db.session() as s:
        u = user(s)
        s.add(Document(id='doc', user_id=u.id, title='Keep me', source_type='txt'))
    try:
        with pytest.raises(RuntimeError), db.engine.begin() as connection:
            config.attributes['connection'] = connection
            command.downgrade(config, '006_retrieval_audit')
        assert 'knowledge_documents' in inspect(db.engine).get_table_names()
    finally:
        db.migrate()
