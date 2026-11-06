"""FastAPI 应用入口。

启动方式：
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.api import system, transcriptions
from app.core.config import get_settings
from app.core.errors import ErrorCode, ApiError
from app.services.model_manager import ModelManager
from app.services.pipeline import TranscriptionPipeline
from app.services.task_store import TaskStore

logger = logging.getLogger("audio2srt")


def _configure_logging() -> None:
    level = os.environ.get("AUDIO2SRT_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()

    model_manager = ModelManager(settings)
    store = TaskStore(settings.task_dir)
    interrupted = store.mark_interrupted()
    if interrupted:
        logger.warning("服务重启，%d 个未完成任务已标记为失败", interrupted)

    pipeline = TranscriptionPipeline(settings, store, model_manager)

    app.state.settings = settings
    app.state.model_manager = model_manager
    app.state.store = store
    app.state.pipeline = pipeline

    logger.info(
        "audio2srt 服务启动: data_dir=%s model_dir=%s workers=%d",
        settings.data_dir,
        settings.model_dir,
        settings.max_workers,
    )
    try:
        yield
    finally:
        pipeline.shutdown()
        logger.info("audio2srt 服务已停止")


def create_app() -> FastAPI:
    _configure_logging()

    app = FastAPI(
        title="audio2srt API",
        description=(
            "把音频/视频转成 SRT 字幕的 HTTP 服务。"
            "模型档位：large-v3-turbo（极速版）、large-v3（专业版）。"
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.include_router(system.router)
    app.include_router(transcriptions.router)

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.INVALID_REQUEST.value,
                    "message": "请求参数校验失败",
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常 path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": "服务内部错误",
                }
            },
        )

    return app


app = create_app()
