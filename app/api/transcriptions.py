"""转写任务相关接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.errors import ApiError, ErrorCode
from app.schemas.task import TaskResponse, TaskStatus
from app.services.pipeline import TranscriptionPipeline
from app.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1/transcriptions", tags=["transcriptions"])


def _pipeline(request: Request) -> TranscriptionPipeline:
    return request.app.state.pipeline


def _store(request: Request) -> TaskStore:
    return request.app.state.store


@router.post(
    "",
    status_code=202,
    response_model=TaskResponse,
    summary="上传音频/视频并创建转写任务",
    response_description="任务已接受，使用 task_id 轮询状态",
)
async def create_transcription(
    request: Request,
    file: Annotated[UploadFile, File(description="音频或视频文件")],
    model: Annotated[str | None, Form(description="模型档位：large-v3-turbo(极速版) / large-v3(专业版)")] = None,
    language: Annotated[str | None, Form(description="语言代码，如 zh/en/ja；auto 或留空为自动检测")] = None,
    output_filename: Annotated[str | None, Form(description="自定义 SRT 文件名（不含路径），可省略 .srt 后缀")] = None,
) -> TaskResponse:
    record = await _pipeline(request).submit(file, model, language, output_filename)
    return TaskResponse.from_record(record)


@router.get("", response_model=list[TaskResponse], summary="列出最近的转写任务")
def list_tasks(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200, description="返回条数上限")] = 50,
) -> list[TaskResponse]:
    return [TaskResponse.from_record(record) for record in _store(request).list(limit)]


@router.get("/{task_id}", response_model=TaskResponse, summary="查询任务状态与结果")
def get_task(request: Request, task_id: str) -> TaskResponse:
    record = _store(request).require(task_id)
    return TaskResponse.from_record(record)


@router.get(
    "/{task_id}/srt",
    summary="下载转写生成的 SRT 文件",
    response_class=FileResponse,
)
def download_srt(request: Request, task_id: str) -> FileResponse:
    record = _store(request).require(task_id)

    if record.status != TaskStatus.COMPLETED:
        raise ApiError(
            ErrorCode.TASK_NOT_COMPLETED,
            f"任务尚未完成，当前状态: {record.status.value}",
            details={"task_id": task_id, "status": record.status.value},
        )

    settings = request.app.state.settings
    path = settings.srt_dir / (record.output_filename or "")
    if not path.is_file():
        raise ApiError(
            ErrorCode.OUTPUT_NOT_FOUND,
            "SRT 文件已不存在（可能被清理）",
            details={"task_id": task_id, "output_filename": record.output_filename},
        )

    return FileResponse(
        path,
        media_type="application/x-subrip",
        filename=record.output_filename,
    )
