"""统一错误码与异常类型。

所有业务错误都以 ``{"error": {"code": "...", "message": "...", "details": ...}}``
返回，便于客户端按 code 分支处理，而不是解析自然语言。
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FFMPEG_NOT_FOUND = "FFMPEG_NOT_FOUND"
    AUDIO_EXTRACTION_FAILED = "AUDIO_EXTRACTION_FAILED"
    UNKNOWN_MODEL = "UNKNOWN_MODEL"
    MODEL_NOT_DOWNLOADED = "MODEL_NOT_DOWNLOADED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    INVALID_OUTPUT_FILENAME = "INVALID_OUTPUT_FILENAME"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_NOT_COMPLETED = "TASK_NOT_COMPLETED"
    OUTPUT_NOT_FOUND = "OUTPUT_NOT_FOUND"
    SERVICE_INTERRUPTED = "SERVICE_INTERRUPTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 错误码 -> 默认 HTTP 状态码
DEFAULT_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.UNSUPPORTED_FORMAT: 415,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.FFMPEG_NOT_FOUND: 503,
    ErrorCode.AUDIO_EXTRACTION_FAILED: 422,
    ErrorCode.UNKNOWN_MODEL: 400,
    ErrorCode.MODEL_NOT_DOWNLOADED: 409,
    ErrorCode.MODEL_LOAD_FAILED: 500,
    ErrorCode.TRANSCRIPTION_FAILED: 500,
    ErrorCode.INVALID_OUTPUT_FILENAME: 400,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.TASK_NOT_COMPLETED: 409,
    ErrorCode.OUTPUT_NOT_FOUND: 410,
    ErrorCode.SERVICE_INTERRUPTED: 500,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ApiError(Exception):
    """业务异常，被全局异常处理器转换为统一 JSON。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        http_status: int | None = None,
        details: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status or DEFAULT_HTTP_STATUS.get(code, 400)
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}
