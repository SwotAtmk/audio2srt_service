"""ffmpeg 定位与音频归一化。

查询优先级与桌面端保持一致：
1. 环境变量 ``FFMPEG_PATH``
2. 项目内置 ``assets/ffmpeg/{mac,win,linux}/ffmpeg``
3. 系统 PATH

差异说明：桌面端在 ``FFMPEG_PATH`` 无效时会静默回退到内置或系统 ffmpeg；
服务端选择直接报错，避免"看起来能跑、实际用错版本"的问题。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.core.errors import ApiError, ErrorCode

BUNDLED_DIR = PROJECT_ROOT / "assets" / "ffmpeg"
FFMPEG_TIMEOUT_SECONDS = 1800


def _bundled_candidates() -> list[Path]:
    system = platform.system().lower()
    if system == "darwin":
        return [BUNDLED_DIR / "mac" / "ffmpeg"]
    if system == "windows":
        return [BUNDLED_DIR / "win" / "ffmpeg.exe"]
    return [BUNDLED_DIR / "linux" / "ffmpeg"]


def _find_ffmpeg_silently() -> str | None:
    """不抛异常地查找 ffmpeg，供 ffprobe 等可选能力使用。"""
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return str(path)
    for candidate in _bundled_candidates():
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def get_ffmpeg_path() -> str:
    """返回可用的 ffmpeg 可执行文件路径，找不到时抛 FFMPEG_NOT_FOUND(503)。"""
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return str(path)
        raise ApiError(
            ErrorCode.FFMPEG_NOT_FOUND,
            f"FFMPEG_PATH 指向的文件不存在: {path}",
            details={"ffmpeg_path_env": env_path},
        )

    for candidate in _bundled_candidates():
        if candidate.is_file():
            return str(candidate)

    system_path = shutil.which("ffmpeg")
    if system_path:
        return system_path

    raise ApiError(
        ErrorCode.FFMPEG_NOT_FOUND,
        "未找到 ffmpeg，请安装 ffmpeg 或设置 FFMPEG_PATH 环境变量（macOS: brew install ffmpeg）",
        details={"checked": [str(p) for p in _bundled_candidates()], "path_lookup": "ffmpeg"},
    )


def get_ffprobe_path() -> str | None:
    """返回 ffprobe 路径；缺失时返回 None（时长探测属于可选能力）。"""
    env_path = os.environ.get("FFPROBE_PATH")
    if env_path and Path(env_path).expanduser().is_file():
        return str(Path(env_path).expanduser())

    ffmpeg = _find_ffmpeg_silently()
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe" if platform.system().lower() == "windows" else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe")


@lru_cache(maxsize=8)
def _ffmpeg_version(binary: str) -> str | None:
    try:
        result = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def ffmpeg_version(binary: str | None = None) -> str | None:
    binary = binary or _find_ffmpeg_silently()
    if not binary:
        return None
    return _ffmpeg_version(binary)


def normalize_audio(input_path: Path, output_path: Path) -> None:
    """把任意音/视频统一转成 16kHz 单声道 PCM WAV（Whisper 的标准输入）。

    桌面端只对视频做提取，音频文件直接交给 whisper（whisper 内部也会调用
    ffmpeg 解码）。服务端统一走一遍 ffmpeg，好处是：格式校验更可控、
    转写输入一致、也能提前暴露损坏文件。
    """
    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-y",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise ApiError(
            ErrorCode.AUDIO_EXTRACTION_FAILED,
            "ffmpeg 处理超时",
            details={"timeout_seconds": FFMPEG_TIMEOUT_SECONDS},
        ) from exc
    except OSError as exc:
        raise ApiError(
            ErrorCode.FFMPEG_NOT_FOUND,
            f"无法执行 ffmpeg: {exc}",
            details={"ffmpeg_path": ffmpeg},
        ) from exc

    if result.returncode != 0:
        raise ApiError(
            ErrorCode.AUDIO_EXTRACTION_FAILED,
            "ffmpeg 音频提取失败，文件可能已损坏或不是有效的音视频格式",
            details={"stderr": (result.stderr or "").strip()[-2000:]},
        )


def probe_duration(path: Path) -> float | None:
    """探测媒体时长（秒），失败时返回 None。"""
    ffprobe = get_ffprobe_path()
    if not ffprobe:
        return None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return round(float(result.stdout.strip()), 3)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None
