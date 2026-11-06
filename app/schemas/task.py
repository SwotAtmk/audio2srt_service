"""任务相关的数据模型与对外响应结构。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class TaskStatus(str, Enum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    TRANSCRIBING = "transcribing"
    WRITING = "writing"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: Any = None


class TaskRecord(BaseModel):
    """持久化到磁盘的内部任务记录。"""

    task_id: str
    status: TaskStatus
    model: str
    language: str | None = None
    original_filename: str
    stored_filename: str
    output_filename: str | None = None
    audio_duration_seconds: float | None = None
    progress: int = 0
    segment_count: int | None = None
    srt_size_bytes: int | None = None
    detected_language: str | None = None
    error: ErrorInfo | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskResponse(BaseModel):
    """对外返回的任务信息（隐藏服务器内部存储路径）。"""

    task_id: str
    status: TaskStatus
    model: str
    language: str | None
    original_filename: str
    output_filename: str | None
    progress: int
    audio_duration_seconds: float | None
    segment_count: int | None
    srt_size_bytes: int | None
    detected_language: str | None
    error: ErrorInfo | None
    download_url: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_record(cls, record: TaskRecord) -> "TaskResponse":
        return cls(
            task_id=record.task_id,
            status=record.status,
            model=record.model,
            language=record.language,
            original_filename=record.original_filename,
            output_filename=record.output_filename,
            progress=record.progress,
            audio_duration_seconds=record.audio_duration_seconds,
            segment_count=record.segment_count,
            srt_size_bytes=record.srt_size_bytes,
            detected_language=record.detected_language,
            error=record.error,
            download_url=(
                f"/api/v1/transcriptions/{record.task_id}/srt"
                if record.status == TaskStatus.COMPLETED
                else None
            ),
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )
