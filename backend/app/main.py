from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from .config import Settings
from .errors import AppError
from starlette.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
import asyncio
import logging
from sqlalchemy.exc import SQLAlchemyError

def envelope(data=None, code=0, message="ok"):
    return {"code": code, "message": message, "data": data}

def create_app(settings: Settings | None = None, gateway=None, accounts=None, wechat=None):
    audit_logger = logging.getLogger('app')
    if not audit_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[levelup] %(name)s %(message)s'))
        audit_logger.addHandler(handler)
    audit_logger.setLevel(logging.INFO)
    if settings is None:
        settings = Settings()
        if settings.database_testing:
            raise RuntimeError('Normal server cannot enable DATABASE_TESTING; use the dedicated test flow')
    @asynccontextmanager
    async def lifespan(app):
        async def cleanup_loop():
            while True:
                if settings.mysql_user:
                    try:
                        await run_in_threadpool(app.state.accounts.cleanup)
                        await run_in_threadpool(app.state.features.cleanup)
                        await run_in_threadpool(app.state.grounding.cleanup)
                    except (SQLAlchemyError, AppError):
                        pass
                await asyncio.sleep(60)
        task = asyncio.create_task(cleanup_loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    app = FastAPI(title="LevelUp API", version="1.1.0", lifespan=lifespan)
    app.state.settings, app.state.gateway = settings, gateway
    from .accounts.database import Database
    from .accounts.repository import Accounts
    from .accounts.wechat import WeChatClient
    app.state.accounts = accounts or Accounts(settings, Database(settings))
    app.state.wechat = wechat or WeChatClient(settings)
    from .materials.repository import Features
    from .materials.sources import Sources
    from .analytics import Analytics
    app.state.features = Features(app.state.accounts)
    app.state.sources = Sources(settings)
    app.state.analytics = Analytics(app.state.accounts)
    from .quiz_grounding.repository import GroundingRepository
    app.state.grounding = GroundingRepository(app.state.accounts)
    @app.middleware('http')
    async def authentication(request, call_next):
        if request.method != 'OPTIONS' and request.url.path.startswith('/api/v1/') and request.url.path not in ('/api/v1/health', '/api/v1/auth/wechat'):
            authorization = request.headers.get('authorization', '')
            if not authorization.startswith('Bearer ') or len(authorization[7:]) < 32:
                return JSONResponse(status_code=401, content=envelope(code='AUTH_REQUIRED', message='请先微信登录'))
            try:
                request.state.user_id = await run_in_threadpool(app.state.accounts.authenticate, authorization[7:])
            except AppError as exc:
                return JSONResponse(status_code=exc.status, content=envelope(code=exc.code, message=exc.message))
            except SQLAlchemyError:
                return JSONResponse(status_code=503, content=envelope(code='DATABASE_UNAVAILABLE', message='数据库暂时无法连接，请稍后重试'))
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['Content-Type', 'Authorization', 'Idempotency-Key'])

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(status_code=exc.status, content=envelope(code=exc.code, message=exc.message))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content=envelope(code="INVALID_INPUT", message="输入格式不正确，请检查文本、题量和作答记录"))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content=envelope(code="NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR", message="接口不存在" if exc.status_code == 404 else "请求无法完成"))

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse(status_code=500, content=envelope(code="INTERNAL_ERROR", message="服务暂时遇到问题，请稍后重试"))

    @app.get("/api/v1/health")
    async def health():
        return envelope({"status":"ok"})

    from .accounts.api import router
    app.include_router(router)
    from .materials.api import router as feature_router
    app.include_router(feature_router)
    from .quiz_grounding.api import router as grounding_router
    app.include_router(grounding_router)
    from .knowledge.api import router as knowledge_router
    app.include_router(knowledge_router)

    return app

app = create_app()
