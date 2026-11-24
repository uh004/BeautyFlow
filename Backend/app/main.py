"""BeautyFlow FastAPI 애플리케이션 진입점 및 팩토리.

실행 명령:
    .venv\\Scripts\\python.exe -m uvicorn Backend.app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from Backend.app.config import BackendSettings, load_settings
from Backend.app.database import create_db_engine, create_session_factory, init_db, recover_interrupted_jobs
from Backend.app.routers import dashboard, jobs
from Backend.app.routers.jobs import APIError
from Backend.app.schemas import ErrorResponse
from Backend.app.services.job_runner import JobRunner


def create_app(
    settings: BackendSettings | None = None,
    pipeline_fn: Callable[..., dict[str, Any]] | None = None,
) -> FastAPI:
    """FastAPI 앱을 생성한다 (테스트 시 임시 DB·Mock AI 주입 가능)."""
    cfg = settings or load_settings()
    engine = create_db_engine(cfg.database_url)
    session_factory = create_session_factory(engine)
    init_db(engine)
    runner = JobRunner(cfg, session_factory, pipeline_fn=pipeline_fn)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        recover_interrupted_jobs(session_factory)
        yield
        runner.shutdown(wait=False)
        engine.dispose()

    app = FastAPI(
        title="BeautyFlow API",
        version="1.0.0",
        description="화장품 상세페이지(PPTX) 기반 AI 숏폼 영상 생성·검증·관리 백엔드 API",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.job_runner = runner

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 공통 오류 응답 핸들러 (error_code, message, job_id)
    @app.exception_handler(APIError)
    async def handle_api_error(_request: Request, exc: APIError):
        payload = ErrorResponse(error_code=exc.error_code, message=exc.message, job_id=exc.job_id).model_dump()
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, _exc: RequestValidationError):
        payload = ErrorResponse(error_code="VALIDATION_ERROR", message="필수 요청 데이터가 누락되었거나 형식이 올바르지 않습니다.").model_dump()
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, _exc: Exception):
        payload = ErrorResponse(error_code="INTERNAL_SERVER_ERROR", message="서버 내부 처리 오류가 발생했습니다.").model_dump()
        return JSONResponse(status_code=500, content=payload)

    app.include_router(dashboard.router)
    app.include_router(jobs.router)
    return app


app = create_app()
