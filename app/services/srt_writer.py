"""SRT 生成与输出文件命名。

命名规则沿用桌面端：
- 未指定输出名 → 用输入文件名 + ``.srt``
- 同名文件已存在 → 追加 6 位随机字符（小写字母 + 数字）

服务端差异：输出目录固定为 ``AUDIO2SRT_DATA_DIR/srt``，接口只接受"文件名"，
不接受任意绝对路径（避免路径穿越和任意写文件）。
"""

from __future__ import annotations

import os
import random
import string
from pathlib import Path

from app.core.errors import ApiError, ErrorCode

_RANDOM_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits


def seconds_to_srt_time(sec: float) -> str:
    """浮点秒数 → ``HH:MM:SS,mmm``。

    桌面端实现直接截断毫秒；这里先四舍五入到毫秒再拆分，
    避免 ``1.999`` 出现 ``00:00:01,999`` 的真实值却因浮点误差少 1ms 的问题。
    """
    total_ms = max(0, int(round(sec * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def build_srt(segments: list[dict]) -> str:
    """把段落列表渲染为 SRT 文本。"""
    blocks: list[str] = []
    for index, seg in enumerate(segments, start=1):
        blocks.append(str(index))
        blocks.append(
            f"{seconds_to_srt_time(seg['start'])} --> {seconds_to_srt_time(seg['end'])}"
        )
        blocks.append(str(seg["text"]).strip())
        blocks.append("")
    return "\n".join(blocks)


def write_srt(segments: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_srt(segments), encoding="utf-8")
    return output_path


def validate_requested_filename(requested: str) -> str:
    name = requested.strip()
    if not name:
        raise ApiError(ErrorCode.INVALID_OUTPUT_FILENAME, "输出文件名不能为空")
    if "/" in name or "\\" in name:
        raise ApiError(
            ErrorCode.INVALID_OUTPUT_FILENAME,
            "output_filename 只能是文件名，不能包含路径分隔符",
            details={"output_filename": requested},
        )
    if name in {".", ".."}:
        raise ApiError(ErrorCode.INVALID_OUTPUT_FILENAME, "非法输出文件名")
    if not name.lower().endswith(".srt"):
        name = f"{name}.srt"
    if name.lower() == ".srt":
        raise ApiError(ErrorCode.INVALID_OUTPUT_FILENAME, "输出文件名缺少主名")
    return name


def reserve_output_path(
    output_dir: Path,
    input_filename: str,
    requested_filename: str | None = None,
) -> Path:
    """确定并"占位"输出文件，返回最终路径。

    使用 O_CREAT|O_EXCL 原子创建空文件，避免并发任务之间的重名竞态；
    任务失败时由调用方删除该占位文件。
    """
    if requested_filename is not None and requested_filename.strip():
        output_name = validate_requested_filename(requested_filename)
        base_name = Path(output_name).stem
    else:
        base_name = Path(input_filename).stem or "output"

    output_dir.mkdir(parents=True, exist_ok=True)

    for attempt in range(100):
        if attempt == 0:
            candidate = output_dir / f"{base_name}.srt"
        else:
            suffix = "".join(random.choices(_RANDOM_SUFFIX_ALPHABET, k=6))
            candidate = output_dir / f"{base_name}_{suffix}.srt"
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        else:
            os.close(fd)
            return candidate

    raise ApiError(
        ErrorCode.INTERNAL_ERROR,
        "无法生成唯一的输出文件名，请稍后重试",
        details={"output_dir": str(output_dir), "base_name": base_name},
    )
