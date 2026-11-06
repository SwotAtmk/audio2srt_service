"""系统信息接口：健康检查、配置、模型列表。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.core import ffmpeg
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.formats import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from app.schemas.system import (
    ConfigResponse,
    FfmpegInfo,
    HealthResponse,
    ModelInfo,
    ModelTier,
    ModelsResponse,
)
from app.services.model_manager import MODEL_REGISTRY, ModelManager
from app.services.pipeline import PROGRESS_BY_STATUS

router = APIRouter(tags=["system"])

API_VERSION = "v1"

PROGRESS_SEMANTICS = (
    "阶段式百分比: "
    + ", ".join(f"{status.value}={value}" for status, value in PROGRESS_BY_STATUS.items())
    + "；openai-whisper 不提供转写过程中的细粒度回调，转写阶段停留在 15"
)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _manager(request: Request) -> ModelManager:
    return request.app.state.model_manager


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health(request: Request) -> HealthResponse:
    settings = _settings(request)
    manager = _manager(request)

    try:
        ffmpeg_path = ffmpeg.get_ffmpeg_path()
        ffmpeg_info = FfmpegInfo(
            ok=True, path=ffmpeg_path, version=ffmpeg.ffmpeg_version(ffmpeg_path)
        )
    except ApiError as exc:
        ffmpeg_info = FfmpegInfo(ok=False, version=None, error=exc.message)

    downloaded = [item["name"] for item in manager.list_models() if item["downloaded"]]
    loaded = [name for name in MODEL_REGISTRY if manager.is_loaded(name)]

    status = "ok" if ffmpeg_info.ok and downloaded else "degraded"

    return HealthResponse(
        status=status,
        service_version=__version__,
        ffmpeg=ffmpeg_info,
        model_dir=str(settings.model_dir),
        downloaded_models=downloaded,
        loaded_models=loaded,
        queue_workers=settings.max_workers,
    )


@router.get("/api/v1/config", response_model=ConfigResponse, summary="查询服务配置")
def get_config(request: Request) -> ConfigResponse:
    settings = _settings(request)

    try:
        ffmpeg_path = ffmpeg.get_ffmpeg_path()
        ffmpeg_ver = ffmpeg.ffmpeg_version(ffmpeg_path)
    except ApiError:
        ffmpeg_path = None
        ffmpeg_ver = None

    return ConfigResponse(
        api_version=API_VERSION,
        service_version=__version__,
        model_dir=str(settings.model_dir),
        data_dir=str(settings.data_dir),
        srt_dir=str(settings.srt_dir),
        default_model=settings.default_model,
        model_device=settings.model_device,
        max_upload_mb=settings.max_upload_mb,
        queue_workers=settings.max_workers,
        ffmpeg_path=ffmpeg_path,
        ffmpeg_version=ffmpeg_ver,
        supported_audio_formats=sorted(AUDIO_EXTENSIONS),
        supported_video_formats=sorted(VIDEO_EXTENSIONS),
        model_tiers=[
            ModelTier(
                name=item["name"],
                display_name=item["display_name"],
                downloaded=item["downloaded"],
                download_url=item["download_url"],
            )
            for item in _manager(request).list_models()
        ],
        progress_semantics=PROGRESS_SEMANTICS,
    )


@router.get("/api/v1/models", response_model=ModelsResponse, summary="查询模型状态")
def list_models(request: Request) -> ModelsResponse:
    manager = _manager(request)
    return ModelsResponse(
        model_dir=str(_settings(request).model_dir),
        models=[ModelInfo(**item) for item in manager.list_models()],
    )
