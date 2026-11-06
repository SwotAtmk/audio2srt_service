"""音频准备：格式校验 + 统一转码为 Whisper 输入格式。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.core import ffmpeg
from app.core.errors import ApiError, ErrorCode
from app.core.formats import SUPPORTED_EXTENSIONS, get_extension, is_supported, is_video


def validate_format(filename: str) -> None:
    if not is_supported(filename):
        raise ApiError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"不支持的文件格式: {get_extension(filename) or '(无扩展名)'}",
            details={"supported_extensions": sorted(SUPPORTED_EXTENSIONS)},
        )


def prepare_audio(input_path: Path, tmp_dir: Path) -> Path:
    """把上传的音/视频转成 16kHz 单声道 WAV，返回临时文件路径。

    ``is_video()`` 仅用于诊断语义，实际对所有输入统一转码。
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(suffix=".wav", prefix="audio2srt_", dir=tmp_dir)
    os.close(fd)
    temp_audio = Path(raw_path)
    try:
        ffmpeg.normalize_audio(input_path, temp_audio)
        return temp_audio
    except Exception:
        cleanup(temp_audio)
        raise


def cleanup(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = ["validate_format", "prepare_audio", "cleanup", "is_video"]
