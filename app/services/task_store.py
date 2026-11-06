"""任务存储：内存索引 + 单任务 JSON 落盘。

为什么不用数据库：单机服务、任务量不大、需要零额外依赖即可运行。
落盘保证服务重启后仍能查询已完成任务的元信息（SRT 文件也在磁盘上）。
若要多进程/多机部署，应替换为 Redis/Celery 或数据库实现（详见接口文档）。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import ApiError, ErrorCode
from app.schemas.task import ErrorInfo, TaskRecord, TaskStatus

TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStore:
    def __init__(self, task_dir: Path):
        self._task_dir = task_dir
        self._task_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._load_from_disk()

    def _task_path(self, task_id: str) -> Path:
        return self._task_dir / f"{task_id}.json"

    def _load_from_disk(self) -> None:
        for path in self._task_dir.glob("*.json"):
            try:
                record = TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                # 损坏的任务文件不影响服务启动，直接跳过
                continue
            self._tasks[record.task_id] = record

    def _persist(self, record: TaskRecord) -> None:
        target = self._task_path(record.task_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(target)

    def create(self, record: TaskRecord) -> TaskRecord:
        with self._lock:
            self._tasks[record.task_id] = record
            self._persist(record)
            return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def require(self, task_id: str) -> TaskRecord:
        record = self.get(task_id)
        if record is None:
            raise ApiError(
                ErrorCode.TASK_NOT_FOUND,
                f"任务不存在: {task_id}",
                details={"task_id": task_id},
            )
        return record

    def update(self, task_id: str, **fields) -> TaskRecord:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise ApiError(
                    ErrorCode.TASK_NOT_FOUND,
                    f"任务不存在: {task_id}",
                    details={"task_id": task_id},
                )
            updated = record.model_copy(update=fields)
            self._tasks[task_id] = updated
            self._persist(updated)
            return updated

    def list(self, limit: int = 50) -> list[TaskRecord]:
        with self._lock:
            records = sorted(
                self._tasks.values(), key=lambda item: item.created_at, reverse=True
            )
            return records[:limit]

    def mark_interrupted(self) -> int:
        """服务重启后，把未完成的任务标记为失败（内存中的执行线程已丢失）。"""
        count = 0
        for record in list(self._tasks.values()):
            if record.status in TERMINAL_STATUSES:
                continue
            self.update(
                record.task_id,
                status=TaskStatus.FAILED,
                error=ErrorInfo(
                    code=ErrorCode.SERVICE_INTERRUPTED.value,
                    message="服务重启，任务被中断，请重新提交",
                ),
                finished_at=utc_now(),
            )
            count += 1
        return count
