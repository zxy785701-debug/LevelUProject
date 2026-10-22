"""Short, authenticated MySQL requests. Heavy work belongs to knowledge.worker."""
from fastapi import APIRouter, Query, Request, UploadFile, File
from starlette.concurrency import run_in_threadpool
from typing import Literal
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from ..accounts.database import utcnow
from ..accounts.repository import stamp
from ..errors import AppError
from .config import load_settings, KnowledgeSettings
from .database import WorkerLease
from .models import DocumentDTO, DocumentPage, ChunkPage, JobDTO, WebImport, MaterialImport,QuestionRequest,QuestionDetail,ScopeRequest,QuizRequest
from .repository import KnowledgeRepository
from ..materials.api import operation_key
from .jobs import DurableJobs
from .worker import storage_identity

router = APIRouter(prefix='/api/v1/knowledge')


def ok(data): return {'code': 0, 'message': 'ok', 'data': data}


def configuration(request):
    injected = getattr(request.app.state, 'knowledge_config', None)
    return (injected, None) if injected is not None else load_settings()


def repository(request, *, processing=False):
    config, error = configuration(request)
    if error or not config.enabled:
        raise AppError(error or 'KNOWLEDGE_DISABLED', '知识库暂未启用，现有学习功能可以继续使用', 503)
    reason = config.unavailable_reason() if processing else None
    if reason:
        raise AppError(reason, '知识库处理服务尚未就绪，请查看服务配置和执行器状态', 503)
    return KnowledgeRepository(request.app.state.accounts, config)


@router.get('/capabilities')
def capabilities(request: Request):
    config, error = configuration(request)
    worker = {'status': 'stopped', 'heartbeat_at': None}
    reason = error or config.unavailable_reason()
    if config and config.enabled:
        try:
            with request.app.state.accounts.database.session() as session:
                row = session.get(WorkerLease, storage_identity(config))
                if row:
                    worker = {'status': 'running' if row.expires_at > utcnow() else 'stopped',
                              'heartbeat_at': stamp(row.heartbeat_at)}
        except (SQLAlchemyError, AppError):
            reason = reason or 'KNOWLEDGE_MIGRATION_REQUIRED'
    if not reason and worker['status'] != 'running': reason = 'KNOWLEDGE_WORKER_UNAVAILABLE'
    return ok({'enabled': bool(config and config.enabled), 'available': reason is None,
               'embedding_available': bool(config and config.embedding_api_key.get_secret_value() and config.embedding_base_url),
               'web_available': request.app.state.settings.tavily_available,
               'reason_code': reason, 'worker': worker,
               'formats': ['pdf', 'docx', 'md', 'markdown', 'txt', 'web'],
               'limits': {'max_bytes': request.app.state.settings.material_max_bytes,
                          'max_documents': config.max_documents if config else 100,
                          'question_max_chars': 6000},
               'disclosure': '文件保存在服务端，正文发送百炼向量化，检索片段发送 DeepSeek。联网补充不会自动提交原始文件或私有片段。'})


@router.get('/documents')
def documents(request: Request, page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100)):
    result = repository(request).documents(request.state.user_id, page, page_size)
    return ok(DocumentPage.model_validate(result).model_dump(mode='json'))


@router.get('/materials')
def material_choices(request: Request,page: int=Query(1,ge=1,le=10000),page_size: int=Query(20,ge=1,le=100)):
    return ok(repository(request).material_choices(request.state.user_id,page,page_size))


@router.get('/job-lookup')
def lookup_job(request: Request,job_type: Literal['import','reindex','prepare','question','quiz'],key: str=Query(min_length=1,max_length=128)):
    result = jobs_repository(request).lookup(request.state.user_id,job_type,key)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.get('/cleanup/{cid}')
def cleanup_status(cid: str,request: Request):
    from .cleanup import LibraryManagement
    repo = jobs_repository(request)
    return ok(LibraryManagement(repo.accounts,repo.config).cleanup_status(request.state.user_id,cid))


@router.post('/documents/upload')
async def upload(request: Request, file: UploadFile = File(...)):
    repo = repository(request, processing=True)
    try:
        data = await file.read(request.app.state.settings.material_max_bytes + 1)
    finally:
        await file.close()
    result = await run_in_threadpool(repo.submit_file, request.state.user_id, operation_key(request), file.filename or 'document', data)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.post('/documents/web')
async def web(body: WebImport, request: Request):
    repo = repository(request, processing=True)
    result = await run_in_threadpool(repo.submit_web, request.state.user_id, operation_key(request), body.url)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.post('/documents/from-material')
def from_material(body: MaterialImport, request: Request):
    result = repository(request, processing=True).submit_material(request.state.user_id, operation_key(request), body.material_id)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.get('/documents/{did}')
def document(did: str, request: Request):
    result = repository(request).document(request.state.user_id, did)
    return ok(DocumentDTO.model_validate(result).model_dump(mode='json'))


@router.get('/documents/{did}/chunks')
def chunks(did: str, request: Request, page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100)):
    result = repository(request).chunks(request.state.user_id, did, page, page_size)
    return ok(ChunkPage.model_validate(result).model_dump(mode='json'))


@router.post('/documents/{did}/reindex')
def reindex_document(did: str, request: Request):
    from .indexing import ImportIndexer
    repo = repository(request,processing=True)
    result = ImportIndexer(repo.accounts,repo.config,None).submit_reindex(request.state.user_id,operation_key(request),did)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.delete('/documents/{did}')
def delete_document(did: str, request: Request):
    from .cleanup import LibraryManagement
    config, error = configuration(request)
    result = LibraryManagement(request.app.state.accounts,config or KnowledgeSettings(_env_file=None)).delete_document(request.state.user_id,did)
    return ok(result)


def jobs_repository(request):
    # Already submitted work remains queryable/cancellable when new entry is disabled.
    config, error = configuration(request)
    return DurableJobs(request.app.state.accounts, config or KnowledgeSettings(_env_file=None))


@router.get('/jobs/{jid}')
def get_job(jid: str, request: Request):
    result = jobs_repository(request).get(request.state.user_id, jid)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.post('/jobs/{jid}/cancel')
def cancel_job(jid: str, request: Request):
    result = jobs_repository(request).cancel(request.state.user_id, jid)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.post('/questions')
def ask_question(body: QuestionRequest, request: Request):
    from .questions import QuestionRepository
    repo = repository(request,processing=True)
    result = QuestionRepository(repo.accounts,repo.config).submit_question(request.state.user_id,operation_key(request),body)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


def questions_repository(request):
    from .questions import QuestionRepository
    config, error = configuration(request)
    return QuestionRepository(request.app.state.accounts,config or KnowledgeSettings(_env_file=None))


@router.get('/questions')
def list_questions(request: Request,page: int=Query(1,ge=1,le=10000),page_size: int=Query(20,ge=1,le=100)):
    return ok(questions_repository(request).list_questions(request.state.user_id,page,page_size))


@router.get('/questions/{qid}')
def get_question(qid: str,request: Request):
    result = questions_repository(request).question(request.state.user_id,qid)
    return ok(QuestionDetail.model_validate(result).model_dump(mode='json'))


@router.delete('/questions/{qid}')
def delete_question(qid: str,request: Request):
    return ok(questions_repository(request).delete_question(request.state.user_id,qid))


@router.get('/questions/{qid}/quiz-context')
def question_quiz_context(qid: str,request: Request):
    return ok(questions_repository(request).quiz_context(request.state.user_id,qid))


@router.post('/quiz-preparations')
def prepare_quiz(body: ScopeRequest,request: Request):
    from .scopes import ScopeRepository
    repo = repository(request,processing=True)
    result = ScopeRepository(repo.accounts,repo.config).submit_preparation(request.state.user_id,operation_key(request),body)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.get('/quiz-preparations/{sid}')
def get_quiz_preparation(sid: str,request: Request):
    from .scopes import ScopeRepository
    config,error = configuration(request)
    return ok(ScopeRepository(request.app.state.accounts,config or KnowledgeSettings(_env_file=None)).get_scope(request.state.user_id,sid))


@router.post('/quizzes')
def generate_quiz(body: QuizRequest,request: Request):
    from .quizzes import QuizRepository
    repo = repository(request,processing=True)
    result = QuizRepository(repo.accounts,repo.config).submit_quiz(request.state.user_id,operation_key(request),body)
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))


@router.post('/jobs/{jid}/retry')
def retry_job(jid: str, request: Request):
    repo = repository(request, processing=True)
    result = DurableJobs(repo.accounts, repo.config).retry(request.state.user_id, jid, operation_key(request))
    return ok(JobDTO.model_validate(result).model_dump(mode='json'))
