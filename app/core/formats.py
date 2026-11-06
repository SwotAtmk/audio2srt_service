"""支持的文件格式定义。"""

from __future__ import annotations

from pathlib import Path

AUDIO_EXTENSIONS = frozenset(
    {
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".opus",
        ".wma",
        ".amr",
        ".aiff",
        ".aif",
        ".mpga",
        ".m4b",
        ".webm",
    }
)

VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".flv",
        ".wmv",
        ".webm",
        ".m4v",
        ".mpeg",
        ".mpg",
        ".ts",
        ".3gp",
    }
)

SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def is_supported(filename: str) -> bool:
    return get_extension(filename) in SUPPORTED_EXTENSIONS


def is_video(filename: str) -> bool:
    return get_extension(filename) in VIDEO_EXTENSIONS
