import asyncio
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, Request, BackgroundTasks, UploadFile, File, Form, Query
from pydantic import Field, model_validator
from starlette.concurrency import run_in_threadpool
from ..models import StrictModel
from ..errors import AppError
from ..llm import ModelGateway
from ..accounts.repository import digest
from .parsers import parse_document, validate_url
from .services import summarize, period_narrative, report_text

router = APIRouter(prefix='/api/v1')
def ok(data): return {'code': 0, 'message': 'ok', 'data': data}


def operation_key(request):
    key = request.headers.get('idempotency-key') or str(uuid4())
    if not 1 <= len(key) <= 128: raise AppError('INVALID_INPUT', '操作标识不正确', 422)
    return key


class LinkBody(StrictModel):
    url: str = Field(min_length=1, max_length=2048)
    learning_instruction: str | None = Field(default=None, min_length=1, max_length=6000)
    start: float = Field(default=0, ge=0, le=86400)
    end: float | None = Field(default=None, gt=0, le=86400)

    @model_validator(mode='after')
    def range_valid(self):
        if self.end is not None and self.end <= self.start: raise ValueError('片段起止时间不正确')
        return self


class PeriodBody(StrictModel):
    days: Literal['7', '30', 'custom'] = '7'
    start: str | None = None
    end: str | None = None
    sections: list[Literal['overview', 'performance', 'advice']] = Field(default_factory=lambda: ['overview', 'performance', 'advice'], min_length=1, max_length=3)

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.sections)) != len(self.sections): raise ValueError('报告内容不能重复')
        return self


async def gateway_for(state, uid, oid, job_id=None):
    if state.gateway is None and not state.settings.deepseek_api_key.get_secret_value(): raise AppError('MODEL_NOT_CONFIGURED', '请先在后端配置 DeepSeek 密钥', 503)
    async def before_call():
        if job_id:
            job = await run_in_threadpool(state.features.job, uid, job_id)
            if job['status'] != 'running': raise AppError('OPERATION_CANCELLED', '解析已取消或过期', 409)
        await run_in_threadpool(state.accounts.model_call, uid, oid)
    from ..quiz_grounding.runtime import counted_gateway
    return counted_gateway(state.settings, state.gateway, before_call, oid)


async def _process_material(state, uid, jid, material=None, body=None, kind=None):
    oid = None
    settled = False
    try:
        if (await run_in_threadpool(state.features.job, uid, jid))['status'] != 'running': return
        oid, _ = await run_in_threadpool(state.accounts.reserve, uid, 'material-'+jid, 'material', {'job_id': jid})
        if material is None:
            from .sources import Sources
            if kind == 'web' and isinstance(state.sources, Sources):
                await run_in_threadpool(state.grounding.generation_tool_call, uid, oid, 'tavily_extract', 0)
                async def before_request():
                    if (await run_in_threadpool(state.features.job, uid, jid))['status'] != 'running':
                        raise AppError('OPERATION_CANCELLED', '网页准备已取消', 409)
                    await run_in_threadpool(state.grounding.operation_page_call, uid, oid, 1)
                material = await state.sources.web(body.url, before_request=before_request)
            else:
                material = await (state.sources.video(body.url, body.start, body.end) if kind == 'video' else state.sources.web(body.url))
        if body and body.learning_instruction:
            material = {**material, 'learning_instruction': body.learning_instruction}
        if (await run_in_threadpool(state.features.job, uid, jid, 'summarizing'))['status'] != 'running': return
        gateway = await gateway_for(state, uid, oid, jid)
        result = await summarize(material, gateway)
        await run_in_threadpool(state.features.job, uid, jid, material=result)
        await run_in_threadpool(state.accounts.finish, uid, oid, {'job_id': jid})
        settled = True
    except asyncio.CancelledError:
        if oid:
            await run_in_threadpool(state.accounts.finish, uid, oid, None, 'OPERATION_EXPIRED')
            settled = True
        try:
            await run_in_threadpool(state.features.job, uid, jid, error=AppError('OPERATION_EXPIRED', '材料准备中断或超时，请重试', 409))
        except AppError:
            pass
        raise
    except Exception as exc:
        error = exc if isinstance(exc, AppError) else AppError('MATERIAL_FAILED', '解析暂时失败，请重试或粘贴正文', 502)
        readable_errors = {'SOURCE_UNAVAILABLE', 'NO_READABLE_CONTENT', 'TAVILY_NOT_CONFIGURED', 'TAVILY_UNAVAILABLE', 'TAVILY_EMPTY', 'TAVILY_TIMEOUT'}
        if oid and material is None and kind == 'web' and body.learning_instruction and error.code in readable_errors:
            try:
                from ..quiz_grounding.preparation import unreadable_page_scope
                gateway = await gateway_for(state, uid, oid, jid)
                fallback = await unreadable_page_scope(body.learning_instruction, gateway)
                if fallback.status == 'ready':
                    await run_in_threadpool(state.grounding.handoff_material, uid, jid, oid, body.learning_instruction, fallback.scope)
                    settled = True
                    return
                error = AppError('LEARNING_TOPIC_REQUIRED', '网页无法读取，请补充独立的学习主题或粘贴正文', 422)
            except Exception as fallback_error:
                error = fallback_error if isinstance(fallback_error, AppError) else AppError('MATERIAL_FAILED', '范围整理失败，请重试', 502)
        if oid:
            await run_in_threadpool(state.accounts.finish, uid, oid, None, error.code)
            settled = True
        try: await run_in_threadpool(state.features.job, uid, jid, error=error)
        except AppError: pass  # Account may have been deleted during extraction.
    finally:
        if oid and not settled:
            # Also release the account lease when cancellation won during source reading.
            await run_in_threadpool(state.accounts.finish, uid, oid, None, 'OPERATION_CANCELLED')


async def process_material(state, uid, jid, material=None, body=None, kind=None):
    try:
        async with asyncio.timeout(state.settings.topic_prepare_timeout_seconds):
            await _process_material(state, uid, jid, material, body, kind)
    except TimeoutError:
        pass  # The inner cancellation handler persisted the terminal failure.


@router.post('/materials/document')
async def document(request: Request, background: BackgroundTasks, file: UploadFile = File(...), pages: str | None = Form(None)):
    settings, uid, state = request.app.state.settings, request.state.user_id, request.app.state
    try: data = await file.read(settings.material_max_bytes + 1)
    finally: await file.close()
    material = await run_in_threadpool(parse_document, file.filename or 'document', data, pages, settings.material_max_bytes, settings.material_max_chars, settings.material_max_pages)
    job, fresh = await run_in_threadpool(state.features.create_job, uid, operation_key(request), {'file': digest(data.hex()), 'name': file.filename, 'pages': pages})
    if fresh: background.add_task(process_material, state, uid, job['id'], material=material)
    return ok(job)


@router.post('/materials/{kind}')
async def link(kind: Literal['web', 'video'], body: LinkBody, request: Request, background: BackgroundTasks):
    await run_in_threadpool(validate_url, body.url)
    if kind == 'video':
        from urllib.parse import urlsplit
        host = urlsplit(body.url).hostname.lower()
        if host not in ('bilibili.com', 'www.bilibili.com', 'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'): raise AppError('UNSUPPORTED_PLATFORM', '本期支持 B站和 YouTube 视频字幕', 422)
    state, uid = request.app.state, request.state.user_id
    job, fresh = await run_in_threadpool(state.features.create_job, uid, operation_key(request), {'kind': kind, **body.model_dump()})
    if fresh: background.add_task(process_material, state, uid, job['id'], body=body, kind=kind)
    return ok(job)


@router.get('/material-jobs/{jid}')
def job(jid: str, request: Request):
    return ok(request.app.state.features.job(request.state.user_id, jid))


@router.post('/material-jobs/{jid}/cancel')
def cancel(jid: str, request: Request):
    return ok(request.app.state.features.job(request.state.user_id, jid, cancel=True))


@router.get('/materials/{mid}')
def material(mid: str, request: Request):
    return ok(request.app.state.features.material(request.state.user_id, mid))


async def generate_from_material(body, request):
    state, uid = request.app.state, request.state.user_id
    from ..quiz_grounding.generation import process_generation
    key = operation_key(request)
    oid, _, fresh, context = await run_in_threadpool(state.grounding.submit_generation, uid, key, body)
    if fresh:
        await process_generation(state, uid, oid, body, context)
    operation = await run_in_threadpool(state.accounts.operation, uid, key)
    if operation['status'] == 'succeeded':
        return operation['result']
    if operation['status'] == 'running':
        raise AppError('AI_BUSY', '该操作仍在生成，请稍后查询原操作', 409)
    code = operation['error_code'] or 'MODEL_INVALID_OUTPUT'
    status = 429 if code in ('AI_RATE_LIMIT', 'DAILY_QUOTA_EXCEEDED') else 422 if code == 'INSUFFICIENT_KNOWLEDGE' else 503 if code in ('MODEL_NOT_CONFIGURED', 'MODEL_AUTH_ERROR', 'MODEL_UNAVAILABLE', 'MODEL_RATE_LIMIT') else 504 if code in ('OPERATION_EXPIRED', 'MODEL_TIMEOUT') else 502
    raise AppError(code, '题目生成未完成，请补充资料或稍后重试', status)


@router.get('/knowledge-map')
def knowledge_map(request: Request): return ok(request.app.state.analytics.map(request.state.user_id))


@router.get('/analytics')
def analytics(request: Request, days: Literal['7', '30', 'all', 'custom'] = '7', start: str | None = None, end: str | None = None):
    return ok(request.app.state.analytics.stats(request.state.user_id, days, start, end))


@router.post('/period-reports')
async def period(body: PeriodBody, request: Request):
    state, uid = request.app.state, request.state.user_id
    snapshot = await run_in_threadpool(state.analytics.snapshot, uid, body.days, body.start, body.end, body.sections)
    report = await run_in_threadpool(state.features.prepare_report, uid, snapshot)
    if report['content']: return ok(report)
    oid, cached = await run_in_threadpool(state.accounts.reserve, uid, operation_key(request), 'period', {'report_id': report['id']}, report['id'])
    if cached is not None: return ok(await run_in_threadpool(state.features.report, uid, report['id']))
    try:
        gateway = await gateway_for(state, uid, oid)
        content = await period_narrative(snapshot, gateway)
        await run_in_threadpool(state.accounts.finish, uid, oid, content)
        return ok(await run_in_threadpool(state.features.report, uid, report['id']))
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else 'MODEL_UNAVAILABLE'
        await run_in_threadpool(state.accounts.finish, uid, oid, None, code)
        raise


@router.get('/period-reports')
def reports(request: Request): return ok(request.app.state.features.reports(request.state.user_id))


@router.get('/period-reports/{rid}')
def report(rid: str, request: Request): return ok(request.app.state.features.report(request.state.user_id, rid))


@router.get('/period-reports/{rid}/export')
def export(rid: str, request: Request):
    data = request.app.state.features.report(request.state.user_id, rid)
    if data['status'] != 'succeeded': raise AppError('REPORT_INCOMPLETE', '报告尚未生成完成', 409)
    return ok({'filename': 'LevelUp-周期学习报告.txt', 'text': report_text(data)})
