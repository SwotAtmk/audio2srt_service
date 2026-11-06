"""openai-whisper 转写封装（服务端版本）。

与桌面端 ``transcriber.py`` 的差异：
- 模型缓存由 ``ModelManager`` 统一管理（单例 + 锁），支持多模型并存
- 增加 per-model 推理锁，避免并发线程同时使用同一个模型实例
- 输出统一归一化为 {start, end, text}，并附带检测到的语言
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.errors import ApiError, ErrorCode
from app.services.model_manager import ModelManager


def transcribe_audio(
    audio_path: Path,
    model_name: str,
    language: str | None,
    model_manager: ModelManager,
) -> dict[str, Any]:
    """执行转写，返回 {segments, language, duration}。

    ``language`` 为 None 或 "auto" 时由 whisper 自动检测。
    """
    model = model_manager.get_model(model_name)

    options: dict[str, Any] = {}
    if language and language != "auto":
        options["language"] = language

    try:
        with model_manager.inference_lock(model_name):
            result = model.transcribe(str(audio_path), **options)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            ErrorCode.TRANSCRIPTION_FAILED,
            f"转写失败: {exc}",
            details={"model": model_name, "error": str(exc)},
        ) from exc

    segments = [
        {
            "start": round(float(seg["start"]), 3),
            "end": round(float(seg["end"]), 3),
            "text": str(seg["text"]).strip(),
        }
        for seg in result.get("segments", [])
        if str(seg.get("text", "")).strip()
    ]

    return {
        "segments": segments,
        "language": result.get("language"),
        "duration": segments[-1]["end"] if segments else 0.0,
    }
