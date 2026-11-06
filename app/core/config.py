"""服务配置 — 全部通过环境变量覆盖，均有可用默认值。

设计取舍：桌面端把配置写在 ~/.audio2srt/config.json；服务端改用环境变量，
更适合容器化与多环境部署，且不依赖可写配置文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# app/core/config.py -> app/core -> app -> 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODEL_DIR = Path.home() / ".audio2srt" / "models"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


@dataclass(frozen=True)
class Settings:
    """运行时配置快照。"""

    data_dir: Path
    model_dir: Path
    default_model: str
    max_upload_mb: int
    max_workers: int
    model_device: str | None
    keep_uploads: bool

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def srt_dir(self) -> Path:
        return self.data_dir / "srt"

    @property
    def task_dir(self) -> Path:
        return self.data_dir / "tasks"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.upload_dir, self.srt_dir, self.task_dir, self.tmp_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    model_dir = Path(_env_str("AUDIO2SRT_MODEL_DIR") or DEFAULT_MODEL_DIR).expanduser()
    data_dir = Path(_env_str("AUDIO2SRT_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()

    return Settings(
        data_dir=data_dir,
        model_dir=model_dir,
        default_model=_env_str("AUDIO2SRT_DEFAULT_MODEL", "large-v3-turbo") or "large-v3-turbo",
        max_upload_mb=_env_int("AUDIO2SRT_MAX_UPLOAD_MB", 500),
        max_workers=max(1, _env_int("AUDIO2SRT_MAX_WORKERS", 1)),
        model_device=_env_str("AUDIO2SRT_MODEL_DEVICE"),
        keep_uploads=os.environ.get("AUDIO2SRT_KEEP_UPLOADS", "").lower() in {"1", "true", "yes"},
    )
