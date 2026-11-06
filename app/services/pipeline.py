"""转写流水线：上传落盘 → 排队 → 后台执行 → 状态流转。

并发模型选择：进程内 ThreadPoolExecutor 单 worker（可配置）。
原因见接口文档：openai-whisper 是 CPU/GPU 密集的同步库，单机部署下单 worker 最稳；
若要多并发，推荐多进程 + 队列，而不是在同一进程里开多线程抢同一个模型实例。
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import UploadFile

from app.core import ffmpeg
from app.core.config import Settings
from app.core.errors import ApiError, ErrorCode
from app.core.formats import get_extension
from app.schemas.task import ErrorInfo, TaskRecord, TaskStatus
from app.services import audio_extractor, srt_writer, transcriber
from app.services.model_manager import ModelManager
from app.services.task_store import TaskStore, utc_now

logger = logging.getLogger("audio2srt.pipeline")

CHUNK_SIZE = 1024 * 1024

# 阶段式进度：whisper 不提供逐段回调，转写中的进度只能给到"阶段"粒度
PROGRESS_BY_STATUS = {
    TaskStatus.QUEUED: 0,
    TaskStatus.EXTRACTING: 5,
    TaskStatus.TRANSCRIBING: 15,
    TaskStatus.WRITING: 95,
    TaskStatus.COMPLETED: 100,
}


class TranscriptionPipeline:
    def __init__(self, settings: Settings, store: TaskStore, model_manager: ModelManager):
        self._settings = settings
        self._store = store
        self._model_manager = model_manager
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_workers,
            thread_name_prefix="audio2srt-worker",
        )

    # ---- 提交阶段（异步，只做 IO 和校验）----
    async def submit(
        self,
        upload: UploadFile,
        model_name: str | None,
        language: str | None,
        output_filename: str | None,
    ) -> TaskRecord:
        original_name = upload.filename or ""

        # 先做廉价校验，避免用户白传一个大文件
        audio_extractor.validate_format(original_name)
        target_model = model_name or self._settings.default_model
        ModelManager.get_spec(target_model)
        if not self._model_manager.is_downloaded(target_model):
            spec = ModelManager.get_spec(target_model)
            raise ApiError(
                ErrorCode.MODEL_NOT_DOWNLOADED,
                f"模型 {target_model}（{spec.display_name}）未下载，请先下载到 {self._settings.model_dir}",
                details={
                    "model": target_model,
                    "expected_path": str(self._model_manager.get_model_path(target_model)),
                    "download_url": spec.url,
                },
            )
        ffmpeg.get_ffmpeg_path()  # 未安装 ffmpeg 时直接 503
        if output_filename:
            srt_writer.validate_requested_filename(output_filename)

        task_id = uuid.uuid4().hex
        ext = get_extension(original_name) or ".bin"
        stored_filename = f"{task_id}{ext}"
        destination = self._settings.upload_dir / stored_filename

        try:
            await self._save_upload(upload, destination)
            output_path = srt_writer.reserve_output_path(
                self._settings.srt_dir, original_name, output_filename
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        normalized_language = None
        if language and language.strip().lower() != "auto":
            normalized_language = language.strip()

        record = TaskRecord(
            task_id=task_id,
            status=TaskStatus.QUEUED,
            model=target_model,
            language=normalized_language,
            original_filename=original_name,
            stored_filename=stored_filename,
            output_filename=output_path.name,
            progress=PROGRESS_BY_STATUS[TaskStatus.QUEUED],
            created_at=utc_now(),
        )
        self._store.create(record)
        self._executor.submit(self._run, task_id)
        logger.info(
            "任务已入队 task_id=%s model=%s file=%s size=%d bytes",
            task_id,
            target_model,
            original_name,
            destination.stat().st_size,
        )
        return record

    async def _save_upload(self, upload: UploadFile, destination: Path) -> None:
        total = 0
        try:
            with destination.open("wb") as fh:
                while chunk := await upload.read(CHUNK_SIZE):
                    total += len(chunk)
                    if total > self._settings.max_upload_bytes:
                        raise ApiError(
                            ErrorCode.FILE_TOO_LARGE,
                            f"文件超过大小限制 {self._settings.max_upload_mb} MB",
                            details={"max_upload_mb": self._settings.max_upload_mb},
                        )
                    fh.write(chunk)
            if total == 0:
                raise ApiError(ErrorCode.INVALID_REQUEST, "上传文件为空")
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    # ---- 执行阶段（同步，跑在线程池里）----
    def _run(self, task_id: str) -> None:
        record = self._store.get(task_id)
        if record is None:  # pragma: no cover
            return

        input_path = self._settings.upload_dir / record.stored_filename
        output_path = self._settings.srt_dir / (record.output_filename or f"{task_id}.srt")
        temp_audio: Path | None = None

        try:
            self._store.update(
                task_id,
                status=TaskStatus.EXTRACTING,
                progress=PROGRESS_BY_STATUS[TaskStatus.EXTRACTING],
                started_at=utc_now(),
            )
            temp_audio = audio_extractor.prepare_audio(input_path, self._settings.tmp_dir)
            duration = ffmpeg.probe_duration(temp_audio)

            self._store.update(
                task_id,
                status=TaskStatus.TRANSCRIBING,
                progress=PROGRESS_BY_STATUS[TaskStatus.TRANSCRIBING],
                audio_duration_seconds=duration,
            )
            result = transcriber.transcribe_audio(
                temp_audio, record.model, record.language, self._model_manager
            )
            segments = result["segments"]

            self._store.update(
                task_id,
                status=TaskStatus.WRITING,
                progress=PROGRESS_BY_STATUS[TaskStatus.WRITING],
                segment_count=len(segments),
                detected_language=result.get("language"),
            )
            srt_writer.write_srt(segments, output_path)

            self._store.update(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=PROGRESS_BY_STATUS[TaskStatus.COMPLETED],
                finished_at=utc_now(),
                srt_size_bytes=output_path.stat().st_size,
            )
            logger.info(
                "任务完成 task_id=%s segments=%d srt=%s",
                task_id,
                len(segments),
                output_path.name,
            )
        except ApiError as exc:
            self._fail(task_id, output_path, exc)
        except Exception as exc:  # 兜底，防止线程池静默吞异常
            logger.exception("任务异常 task_id=%s", task_id)
            self._fail(
                task_id,
                output_path,
                ApiError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    f"转写失败: {exc}",
                    details={"error": str(exc)},
                ),
            )
        finally:
            audio_extractor.cleanup(temp_audio)
            if not self._settings.keep_uploads:
                input_path.unlink(missing_ok=True)

    def _fail(self, task_id: str, output_path: Path, exc: ApiError) -> None:
        try:
            output_path.unlink(missing_ok=True)  # 删除占位或半成品 SRT
        except OSError:  # pragma: no cover
            pass
        self._store.update(
            task_id,
            status=TaskStatus.FAILED,
            error=ErrorInfo(
                code=exc.code.value, message=exc.message, details=exc.details
            ),
            finished_at=utc_now(),
        )
        logger.warning("任务失败 task_id=%s code=%s message=%s", task_id, exc.code.value, exc.message)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        # 未开始/被取消的任务不会再有线程执行，直接标记为失败
        self._store.mark_interrupted()
