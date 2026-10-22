import asyncio
import pytest
from app.errors import AppError
from tests.test_knowledge_index import index,staged
from tests.test_knowledge_repository import repo
from tests.test_knowledge_budgets import ai_job


def ready(repo,index):
    from app.knowledge.database import Revision,Document
    pipeline,claim,parsed,chunks = staged(repo)
    index.upsert(claim,parsed['revision_id'],chunks,[[1.0]*1024])
    with repo.database.session() as session:
        session.get(Revision,parsed['revision_id']).status = 'ready'
        document = session.get(Document,claim.document_id)
        document.active_revision_id,document.status = parsed['revision_id'],'ready'
    pipeline.complete(claim,lambda s,j:{'document_id':claim.document_id})
    return repo.select_documents('alice',[claim.document_id])


def test_retrieval_checkpoints_restore_only_original_owned_document_versions(index,repo):
    from app.knowledge.retrieval_store import KnowledgeRetriever
    from app.knowledge.database import Job,Document
    from app.knowledge.evidence import evidence_from_hit
    selected = ready(repo,index)
    jid = ai_job(repo)
    with repo.database.session() as session: session.get(Job,jid).payload = {'documents':selected,'question':'原始问题'}
    queries = []
    class Embeddings:
        async def aembed_query(self,text): queries.append(text); return [1.0]*1024
    retrieval = KnowledgeRetriever(repo.accounts,repo.config,index,embedding_factory=lambda claim:Embeddings())
    claim = retrieval.claim('worker')
    result = asyncio.run(retrieval.retrieve(claim,'原始问题',selected,allow_web=False))
    assert result.evidence[0].text=='Original content' and queries==['原始问题']
    restored = asyncio.run(KnowledgeRetriever(repo.accounts,repo.config,index,embedding_factory=lambda claim:Embeddings()).retrieve(claim,'原始问题',selected,allow_web=False))
    assert restored.evidence==result.evidence and len(queries)==1
    with pytest.raises(AppError): asyncio.run(retrieval.retrieve(claim,'变更后的问题',selected,allow_web=False))
    with pytest.raises(AppError): asyncio.run(retrieval.retrieve(claim,'原始问题',selected,allow_web=True))
    with repo.database.session() as session: session.get(Document,selected[0]['id']).deleted_at = repo.now()
    with pytest.raises(AppError): asyncio.run(retrieval.retrieve(claim,'原始问题',selected,allow_web=False))


def test_index_errors_are_recorded_without_guessing_content_and_scope_failure_can_finish(index,repo,monkeypatch):
    from app.knowledge.retrieval_store import KnowledgeRetriever
    from app.knowledge.database import Job,Document
    selected = ready(repo,index)
    jid = ai_job(repo)
    with repo.database.session() as session: session.get(Job,jid).payload = {'documents':selected}
    class Embeddings:
        async def aembed_query(self,text): return [1.0]*1024
    retrieval = KnowledgeRetriever(repo.accounts,repo.config,index,embedding_factory=lambda claim:Embeddings())
    claim = retrieval.claim('worker')
    monkeypatch.setattr(index,'search',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('private disk path')))
    result = asyncio.run(retrieval.retrieve(claim,'资料',selected,allow_web=False))
    assert not result.evidence and result.knowledge_error=='KNOWLEDGE_INDEX_UNAVAILABLE'
    with repo.database.session() as session: session.get(Document,selected[0]['id']).deleted_at = repo.now()
    retrieval.fail(claim,'KNOWLEDGE_VERSION_CHANGED','资料已变化')
    assert retrieval.get('alice',jid)['status']=='failed'
