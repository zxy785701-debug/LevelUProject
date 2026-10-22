from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import delete
from app.accounts.database import Database, Base, utcnow
from app.accounts.repository import Accounts
from app.config import Settings
from app.errors import AppError
from app.knowledge.config import KnowledgeSettings
from tests.knowledge_support import assert_database, assert_test_boundary
from tests.test_knowledge_database import user


@pytest.fixture
def repo(tmp_path):
    from app.knowledge.repository import KnowledgeRepository
    settings = Settings(database_testing=True, wechat_app_id='knowledge-test', identity_hash_secret='knowledge-test-secret-'*3)
    database = Database(settings)
    with database.engine.connect() as connection:
        actual = assert_database(settings, connection)
    assert_test_boundary(settings, actual, tmp_path/'knowledge', tmp_path)
    database.migrate()
    with database.engine.begin() as connection:
        assert_database(settings, connection)
        for table in reversed(Base.metadata.sorted_tables): connection.execute(delete(table))
    accounts = Accounts(settings, database)
    with database.session() as s:
        user(s, 'alice')
        user(s, 'bob')
    value = KnowledgeRepository(accounts, KnowledgeSettings(_env_file=None, storage_root=tmp_path/'knowledge'))
    yield value
    database.engine.dispose()


def seed(repo, uid='alice', did='doc', *, ready=True, deleted=False):
    from app.knowledge.database import Document, Revision, Chunk
    rid = 'rev-' + did
    with repo.database.session() as s:
        s.add(Document(id=did, user_id=uid, title='真实资料 ' + did, source_type='md', source={'filename': did+'.md'},
                       status='ready' if ready else 'processing', active_revision_id=rid if ready else None,
                       deleted_at=utcnow() if deleted else None))
        s.flush()
        s.add(Revision(id=rid, document_id=did, number=1, profile=repo.profile, status='ready' if ready else 'staging', text='Original document'))
        s.flush()
        s.add(Chunk(id='chunk-'+did, revision_id=rid, position=0, text='Original document', content_hash='a'*64,
                    location={'header_path': ['标题'], 'start_index': 0, 'end_index': 17}))
    return did, rid


def test_owned_pagination_and_deleted_filtering(repo):
    seed(repo)
    seed(repo, did='second')
    seed(repo, uid='bob', did='private')
    seed(repo, did='removed', deleted=True)
    page = repo.documents('alice', page=1, page_size=1)
    assert page['total'] == 2 and len(page['items']) == 1
    assert page['items'][0]['id'] != repo.documents('alice', page=2, page_size=1)['items'][0]['id']
    for did in ('private', 'removed', 'missing'):
        with pytest.raises(AppError) as exc: repo.document('alice', did)
        assert exc.value.status == 404
    assert repo.documents('bob')['total'] == 1


@pytest.mark.parametrize('page,size', [(0, 20), (1, 0), (1, 101), (True, 20), (10001, 20)])
def test_pagination_is_bounded(repo, page, size):
    with pytest.raises(AppError) as exc: repo.documents('alice', page=page, page_size=size)
    assert exc.value.status == 422


def test_only_active_owned_ready_revision_is_previewed(repo):
    from app.knowledge.database import Revision, Chunk
    seed(repo)
    with repo.database.session() as s:
        s.add(Revision(id='staging', document_id='doc', number=2, profile=repo.profile, text='Unpublished'))
        s.flush()
        s.add(Chunk(id='unpublished', revision_id='staging', position=0, text='Unpublished', content_hash='b'*64, location={}))
    result = repo.chunks('alice', 'doc')
    assert [c['text'] for c in result['items']] == ['Original document']
    assert result['items'][0]['location']['header_path'] == ['标题']
    assert 'storage_root' not in str(repo.document('alice', 'doc'))
    with pytest.raises(AppError): repo.chunks('bob', 'doc')


def test_selection_is_explicit_and_binds_ready_owned_versions(repo):
    seed(repo)
    seed(repo, uid='bob', did='private')
    seed(repo, did='pending', ready=False)
    for ids in ([], ['private'], ['pending'], ['doc','doc']):
        with pytest.raises(AppError): repo.select_documents('alice', ids)
    selection = repo.select_documents('alice', ['doc'])
    assert selection[0]['revision_id'] == 'rev-doc' and selection[0]['version'] == 1
    assert [d['id'] for d in repo.select_documents('alice', [], all_ready=True)] == ['doc']
    from app.knowledge.database import Document
    with repo.database.session() as s: s.get(Document, 'doc').deleted_at = utcnow()
    with pytest.raises(AppError): repo.validate_documents('alice', selection)


def test_concurrent_version_change_invalidates_a_previously_selected_scope(repo):
    from concurrent.futures import ThreadPoolExecutor
    from app.knowledge.database import Document, Revision
    seed(repo)
    selection = repo.select_documents('alice', ['doc'])
    def switch():
        with repo.database.session() as s:
            repo.accounts._user(s, 'alice', True)
            s.add(Revision(id='new-revision', document_id='doc', number=2, profile=repo.profile, status='ready'))
            s.flush()
            s.get(Document, 'doc').active_revision_id = 'new-revision'
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(switch).result(timeout=10)
    with pytest.raises(AppError) as exc: repo.validate_documents('alice', selection)
    assert exc.value.code == 'KNOWLEDGE_VERSION_CHANGED'
