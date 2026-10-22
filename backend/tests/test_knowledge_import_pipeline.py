import asyncio
from copy import deepcopy
import pytest
from sqlalchemy import select,func,event
from sqlalchemy.orm import Session
from app.errors import AppError
from app.materials.sources import Sources
from tests.test_grounding_tavily import wire,settings
from tests.test_knowledge_repository import repo
from tests.test_knowledge_jobs import submit


@pytest.mark.anyio
async def test_web_import_uses_requested_actual_body_with_fetch_time_and_truncation(wire):
    from app.knowledge.importing import fetch_web
    wire['body'] = {'results':[{'url':'https://example.com/','title':'真实页面','raw_content':'真实正文。'*1200}]}
    source = Sources(settings(tool_result_max_bytes=1024))
    calls = []
    async def before(): calls.append(True)
    result = await fetch_web('https://example.com/',source,before_request=before)
    assert result['source_type'] == 'web' and result['url'] == 'https://example.com/'
    assert result['retrieved_at'] and result['truncated'] and result['source_chars'] > len(result['text'])
    assert calls == [True] and len(wire['calls']) == 1
    assert wire['calls'][0]['body']['urls'] == ['https://example.com/']
    assert 'query' not in wire['calls'][0]['body']


@pytest.mark.anyio
@pytest.mark.parametrize('row',[
    {'url':'https://example.com/','content':'A summary cannot become a document'},
    {'url':'http://127.0.0.1/private','raw_content':'private redirect'},
    {'url':'https://different.example/','raw_content':'unrequested redirect'},
])
async def test_summary_or_unrequested_redirect_cannot_be_imported(wire,row):
    from app.knowledge.importing import fetch_web
    wire['body'] = {'results':[row]}
    with pytest.raises(AppError): await fetch_web('https://example.com/',Sources(settings()))


def test_parsing_checkpoint_survives_process_reconstruction_without_new_revision_or_file_read(repo,monkeypatch):
    from app.knowledge.importing import ImportPipeline
    from app.knowledge.database import Revision,Chunk
    from app.knowledge.files import FileStore
    row = submit(repo)
    pipeline = ImportPipeline(repo.accounts,repo.config)
    claim = pipeline.claim('worker')
    parsed = pipeline.parse(claim)
    FileStore(repo.config.storage_root).delete('alice',claim.payload['file_path'])
    fresh = ImportPipeline(repo.accounts,repo.config)
    assert fresh.parse(claim) == parsed
    chunks = fresh.split(claim,parsed)
    assert fresh.split(claim,parsed) == chunks
    with repo.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Revision)) == 1
        assert session.scalar(select(func.count()).select_from(Chunk)) == len(chunks)
    assert pipeline.get('alice',row['id'])['progress'] == 35
    assert 'file_path' not in str(repo.document('alice',row['document_id']))


def test_staging_commit_failure_rolls_back_and_retry_is_deterministic(repo):
    from app.knowledge.importing import ImportPipeline
    from app.knowledge.database import Revision
    submit(repo)
    pipeline = ImportPipeline(repo.accounts,repo.config)
    claim = pipeline.claim('worker')
    def fail(session):
        if any(isinstance(value,Revision) for value in session.identity_map.values()) or any(isinstance(value,Revision) for value in session.new):
            raise RuntimeError('simulated database commit interruption')
    event.listen(Session,'before_commit',fail)
    try:
        with pytest.raises(RuntimeError): pipeline.parse(claim)
    finally: event.remove(Session,'before_commit',fail)
    with repo.database.session() as session: assert session.scalar(select(func.count()).select_from(Revision)) == 0
    assert pipeline.parse(claim)['text'] == 'Original content'


def test_total_text_limit_and_changed_file_are_rejected_before_embedding(repo):
    from app.knowledge.importing import ImportPipeline
    from app.knowledge.files import FileStore
    submit(repo)
    pipeline = ImportPipeline(repo.accounts,repo.config)
    claim = pipeline.claim('worker')
    repo.config.max_total_chars = 5
    with pytest.raises(AppError) as error: pipeline.parse(claim)
    assert error.value.code == 'KNOWLEDGE_TEXT_LIMIT'
    repo.config.max_total_chars = 5000000
    path = FileStore(repo.config.storage_root)._path('alice',claim.payload['file_path'])
    path.write_bytes(b'changed after receiving')
    with pytest.raises(AppError) as error: pipeline.parse(claim)
    assert error.value.code == 'KNOWLEDGE_FILE_CHANGED'
