import copy
import pytest
from sqlalchemy import select
from app.accounts.database import Material
from app.errors import AppError
from tests.test_knowledge_repository import repo


def test_file_submission_is_durable_idempotent_and_does_not_spend_quiz_quota(repo):
    from app.knowledge.database import Document, Job
    from app.knowledge.files import FileStore
    result = repo.submit_file('alice', 'upload-key', '../../自己的笔记.md', '# 学习\n原始正文'.encode())
    assert result['kind'] == 'knowledge_job' and result['status'] == 'queued' and result['progress'] == 0
    assert result['document_id']
    again = repo.submit_file('alice', 'upload-key', '../../自己的笔记.md', '# 学习\n原始正文'.encode())
    assert again['id'] == result['id']
    with pytest.raises(AppError) as exc: repo.submit_file('alice', 'upload-key', 'other.md', b'# different')
    assert exc.value.status == 409
    with repo.database.session() as s:
        doc, job = s.get(Document, result['document_id']), s.get(Job, result['id'])
        assert doc.title == '自己的笔记.md' and doc.source_type == 'md'
        assert FileStore(repo.config.storage_root).read('alice', job.payload['file_path']) == '# 学习\n原始正文'.encode()
        assert repo.accounts._quota(s, s.get(__import__('app.accounts.database', fromlist=['User']).User, 'alice').identity).quiz_count == 0


@pytest.mark.parametrize('name,data', [('old.doc', b'x'), ('fake.pdf', b'not pdf'), ('bad.docx', b'not zip'),
                                     ('binary.md', b'\x00binary'), ('empty.txt', b''), ('huge.txt', b'x'*(20*1024*1024+1))],
                         ids=['legacy-doc', 'fake-pdf', 'fake-docx', 'binary', 'empty', 'oversize'])
def test_invalid_files_are_rejected_before_persistence(repo, name, data):
    with pytest.raises(AppError): repo.submit_file('alice', 'invalid', name, data)
    assert repo.documents('alice')['total'] == 0
    assert not repo.config.storage_root.exists()


def test_web_submission_validates_public_url_before_queued_work(repo, monkeypatch):
    import app.knowledge.repository as module
    from app.materials.parsers import validate_url
    monkeypatch.setattr(module, 'validate_url', lambda url: validate_url(url, resolve=lambda _: ['93.184.216.34']))
    result = repo.submit_web('alice', 'web', 'https://example.org/a')
    assert result['status'] == 'queued'
    monkeypatch.setattr(module, 'validate_url', lambda url: validate_url(url, resolve=lambda _: ['127.0.0.1']))
    with pytest.raises(AppError): repo.submit_web('alice', 'bad-web', 'http://localhost/private')
    assert repo.documents('alice')['total'] == 1


def test_owned_material_is_copied_before_its_temporary_record_is_removed(repo):
    from app.knowledge.database import Job
    original = {'title': '旧资料', 'source_type': 'txt', 'segments': [{'id':'s1','text':'独立保留的正文'}]}
    with repo.database.session() as s:
        s.add(Material(id='source', user_id='alice', content=copy.deepcopy(original)))
    with pytest.raises(AppError): repo.submit_material('bob', 'copy', 'source')
    result = repo.submit_material('alice', 'copy', 'source')
    with repo.database.session() as s: s.delete(s.get(Material, 'source'))
    assert repo.submit_material('alice', 'copy', 'source')['id'] == result['id']
    with repo.database.session() as s:
        assert s.get(Job, result['id']).payload['material_content']['segments'][0]['text'] == '独立保留的正文'


def test_import_limits_are_serialized_and_idempotent_replays_remain_available(repo):
    from concurrent.futures import ThreadPoolExecutor
    repo.config.import_daily_limit = 1
    def submit(index):
        try: return repo.submit_file('alice', 'limit-'+str(index), 'note.txt', b'Content')
        except AppError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(submit, [1,2]))
    assert sum(isinstance(value, dict) for value in results) == 1
    assert 'KNOWLEDGE_IMPORT_DAILY_LIMIT' in results
    assert repo.documents('alice')['total'] == 1


def test_private_filestore_rejects_client_paths_and_unmarked_existing_directories(tmp_path):
    from app.knowledge.files import FileStore
    root = tmp_path/'files'
    root.mkdir()
    (root/'personal.txt').write_text('keep this')
    with pytest.raises(AppError): FileStore(root, create=True)
    storage = FileStore(tmp_path/'private', create=True)
    path = storage.save('alice', b'original')
    for candidate in ('../personal.txt', '/etc/passwd', path.replace('files/', '../'), 'files/nope/name.bin'):
        with pytest.raises(AppError): storage.read('alice', candidate)
    with pytest.raises(AppError): storage.read('bob', path)
    assert (root/'personal.txt').read_text() == 'keep this'
