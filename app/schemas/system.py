"""系统信息相关响应模型。"""

from __future__ import annotations

from pydantic import BaseModel


class ModelInfo(BaseModel):
    name: str
    display_name: str
    downloaded: bool
    loaded: bool
    path: str
    size_bytes: int | None
    download_url: str


class ModelsResponse(BaseModel):
    model_dir: str
    models: list[ModelInfo]


class FfmpegInfo(BaseModel):
    ok: bool
    path: str | None = None
    version: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    service_version: str
    ffmpeg: FfmpegInfo
    model_dir: str
    downloaded_models: list[str]
    loaded_models: list[str]
    queue_workers: int


class ModelTier(BaseModel):
    name: str
    display_name: str
    downloaded: bool
    download_url: str


class ConfigResponse(BaseModel):
    api_version: str
    service_version: str
    model_dir: str
    data_dir: str
    srt_dir: str
    default_model: str
    model_device: str | None
    max_upload_mb: int
    queue_workers: int
    ffmpeg_path: str | None
    ffmpeg_version: str | None
    supported_audio_formats: list[str]
    supported_video_formats: list[str]
    model_tiers: list[ModelTier]
    progress_semantics: str
