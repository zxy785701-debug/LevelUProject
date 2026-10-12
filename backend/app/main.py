from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from .config import Settings
from .errors import AppError
from .models import GenerateRequest, ReportRequest
from .content import check_content

def envelope(data=None, code=0, message="ok"):
    return {"code": code, "message": message, "data": data}

def create_app(settings: Settings | None = None, gateway=None):
    settings = settings or Settings()
    app = FastAPI(title="LevelUp API", version="1.0.0")
    app.state.settings, app.state.gateway = settings, gateway
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

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

    @app.post("/api/v1/quiz/generate")
    async def quiz(body: GenerateRequest):
        check_content(body.text)
        if not settings.deepseek_api_key.get_secret_value() and gateway is None:
            raise AppError("MODEL_NOT_CONFIGURED", "请先在后端配置 DeepSeek 密钥", 503)
        from .services import generate_quiz
        return envelope(await generate_quiz(body, settings, gateway))

    @app.post("/api/v1/report/generate")
    async def report(body: ReportRequest):
        if not settings.deepseek_api_key.get_secret_value() and gateway is None:
            raise AppError("MODEL_NOT_CONFIGURED", "请先在后端配置 DeepSeek 密钥", 503)
        from .services import generate_report
        return envelope(await generate_report(body, settings, gateway))

    return app

app = create_app()
