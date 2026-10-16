from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, Request, UploadFile, File, Query, BackgroundTasks
from fastapi.responses import Response
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from ..models import StrictModel, GenerateRequest, ReportRequest, Answer
from ..errors import AppError
from ..content import check_content
from ..llm import ModelGateway
from ..services import generate_quiz, generate_report
from ..quiz_grounding.models import GenerateEnvelope

router = APIRouter(prefix='/api/v1')

def ok(data=None):
    return {'code': 0, 'message': 'ok', 'data': data}

class LoginBody(StrictModel):
    code: str = Field(min_length=1, max_length=256)
    agreement_version: str = Field(pattern=r'^2026-10-12$')

class NicknameBody(StrictModel):
    nickname: str = Field(min_length=1, max_length=32)

class AttemptBody(StrictModel):
    quiz_id: str = Field(min_length=1, max_length=36)

class ReportBody(StrictModel):
    attempt_id: str = Field(min_length=1, max_length=36)

class ReviewBody(StrictModel):
    keys: list[str] = Field(min_length=1, max_length=100)

class ProgressBody(StrictModel):
    cursor: int = Field(ge=0, le=100, strict=True)

class WrongBody(StrictModel):
    key: str = Field(min_length=1, max_length=180)
    mastered: bool

class DeleteBody(StrictModel):
    code: str = Field(min_length=1, max_length=256)
    confirmation: str = Field(pattern=r'^注销账号$')

@router.post('/auth/wechat')
async def login(body: LoginBody, request: Request):
    a = request.app.state.accounts
    await run_in_threadpool(a.login_rate, request.client.host if request.client else 'unknown')
    identity = await request.app.state.wechat.exchange(body.code)
    return ok(await run_in_threadpool(a.login, identity, body.agreement_version))

@router.post('/auth/logout')
def logout(request: Request):
    request.app.state.accounts.logout(request.headers['authorization'][7:])
    return ok()

@router.get('/me')
def me(request: Request):
    return ok(request.app.state.accounts.me(request.state.user_id))

@router.patch('/me')
@router.put('/me')
def nickname(body: NicknameBody, request: Request):
    return ok(request.app.state.accounts.nickname(request.state.user_id, body.nickname))

@router.post('/me/avatar')
async def avatar_upload(request: Request, file: UploadFile = File(...)):
    data = await file.read(2 * 1024 * 1024 + 1)
    return ok(await run_in_threadpool(request.app.state.accounts.avatar, request.state.user_id, data))

@router.get('/me/avatar')
def avatar(request: Request):
    return Response(request.app.state.accounts.avatar(request.state.user_id), media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})

@router.get('/learning')
def learning(request: Request):
    return ok(request.app.state.accounts.learning(request.state.user_id))

@router.get('/attempts')
def history(request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: Literal['all', 'completed', 'unfinished'] = 'all', mode: Literal['all', 'new', 'replay', 'review'] = 'all', days: Literal['all', '7', '30'] = 'all'):
    return ok(request.app.state.accounts.history(request.state.user_id, page, page_size, status, mode, days))

@router.get('/attempts/{aid}')
def attempt(aid: str, request: Request):
    return ok(request.app.state.accounts.attempt(request.state.user_id, aid))

@router.delete('/attempts/{aid}')
def delete_attempt(aid: str, request: Request):
    return ok(request.app.state.accounts.delete_attempt(request.state.user_id, aid))

@router.post('/attempts')
def replay(body: AttemptBody, request: Request):
    return ok(request.app.state.accounts.replay(request.state.user_id, body.quiz_id))

@router.post('/attempts/review')
def review(body: ReviewBody, request: Request):
    if len(set(body.keys)) != len(body.keys): raise AppError('INVALID_INPUT', '错题不能重复', 422)
    return ok(request.app.state.accounts.review(request.state.user_id, body.keys))

@router.post('/attempts/{aid}/answers')
def answer(aid: str, body: Answer, request: Request):
    return ok(request.app.state.accounts.answer(request.state.user_id, aid, body.model_dump()))

@router.patch('/attempts/{aid}/progress')
@router.put('/attempts/{aid}/progress')
def progress(aid: str, body: ProgressBody, request: Request):
    return ok(request.app.state.accounts.progress(request.state.user_id, aid, body.cursor))

@router.patch('/wrongs')
@router.put('/wrongs')
def wrong(body: WrongBody, request: Request):
    request.app.state.accounts.wrong(request.state.user_id, body.key, body.mastered)
    return ok()

@router.post('/wrongs/clear')
def clear_wrongs(request: Request):
    request.app.state.accounts.wrong(request.state.user_id)
    return ok()

@router.get('/me/export')
def export(request: Request):
    return Response(request.app.state.accounts.export(request.state.user_id), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=levelup-learning.csv'})

@router.post('/me/delete')
async def delete_account(body: DeleteBody, request: Request):
    identity = await request.app.state.wechat.exchange(body.code)
    await run_in_threadpool(request.app.state.accounts.delete_account, request.state.user_id, identity)
    return ok()

@router.get('/operations/{key}')
def operation(key: str, request: Request):
    return ok(request.app.state.accounts.operation(request.state.user_id, key))

async def run_ai(request, kind, payload, aid=None):
    state = request.app.state
    a, uid = state.accounts, request.state.user_id
    key = request.headers.get('idempotency-key') or str(uuid4())
    if not 1 <= len(key) <= 128: raise AppError('INVALID_INPUT', '操作标识不正确', 422)
    oid, cached = await run_in_threadpool(a.reserve, uid, key, kind, payload, aid)
    if cached is not None: return cached
    try:
        if not state.settings.deepseek_api_key.get_secret_value() and state.gateway is None:
            raise AppError('MODEL_NOT_CONFIGURED', '请先在后端配置 DeepSeek 密钥', 503)
        async def before_call():
            await run_in_threadpool(a.model_call, uid, oid)
        from ..quiz_grounding.runtime import counted_gateway
        gateway = counted_gateway(state.settings, state.gateway, before_call, oid)
        if kind == 'quiz':
            quiz = await generate_quiz(GenerateRequest.model_validate(payload), state.settings, gateway)
            result = await run_in_threadpool(a.store_quiz, uid, quiz, oid)
        else:
            trusted = await run_in_threadpool(a.report_input, uid, aid)
            result = await generate_report(ReportRequest.model_validate(trusted), state.settings, gateway)
            await run_in_threadpool(a.finish, uid, oid, result)
        return result
    except Exception as exc:
        await run_in_threadpool(a.finish, uid, oid, None, exc.code if isinstance(exc, AppError) else 'MODEL_UNAVAILABLE')
        raise

@router.post('/quiz/generate', response_model=GenerateEnvelope)
async def quiz(body: GenerateRequest, request: Request, background: BackgroundTasks):
    if body.text:
        check_content(body.text)
        raise AppError('SCOPE_CONFIRMATION_REQUIRED', '请先准备并确认学习范围', 409)
    if body.material_id and body.execution == 'sync':
        from ..materials.api import generate_from_material
        return ok(await generate_from_material(body, request))
    from ..materials.api import operation_key
    from ..quiz_grounding.generation import process_generation
    state, uid = request.app.state, request.state.user_id
    oid, operation, fresh, context = await run_in_threadpool(state.grounding.submit_generation, uid, operation_key(request), body)
    if fresh:
        background.add_task(process_generation, state, uid, oid, body, context)
    return ok(operation)

@router.post('/report/generate')
async def report(body: ReportBody, request: Request):
    return ok(await run_ai(request, 'report', body.model_dump(), body.attempt_id))
