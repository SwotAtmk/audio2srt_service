"""SRT 生成与输出命名单元测试。"""

from __future__ import annotations

import re

import pytest

from app.core.errors import ApiError, ErrorCode
from app.services.srt_writer import (
    build_srt,
    reserve_output_path,
    seconds_to_srt_time,
    validate_requested_filename,
)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (61.234, "00:01:01,234"),
        (3661.999, "01:01:01,999"),
        (0.0009, "00:00:00,001"),
        (-1, "00:00:00,000"),
    ],
)
def test_seconds_to_srt_time(seconds, expected):
    assert seconds_to_srt_time(seconds) == expected


def test_build_srt():
    segments = [
        {"start": 0.0, "end": 1.5, "text": " 第一句 "},
        {"start": 1.5, "end": 4.0, "text": "第二句"},
    ]
    content = build_srt(segments)
    assert "1\n00:00:00,000 --> 00:00:01,500\n第一句" in content
    assert "2\n00:00:01,500 --> 00:00:04,000\n第二句" in content


def test_reserve_default_name(tmp_path):
    path = reserve_output_path(tmp_path, "demo.mp3")
    assert path.name == "demo.srt"
    assert path.exists() and path.stat().st_size == 0


def test_reserve_appends_six_random_chars_on_collision(tmp_path):
    first = reserve_output_path(tmp_path, "demo.mp3")
    second = reserve_output_path(tmp_path, "demo.mp3")
    assert second.name != first.name
    assert re.fullmatch(r"demo_[a-z0-9]{6}\.srt", second.name), second.name


def test_reserve_custom_filename(tmp_path):
    path = reserve_output_path(tmp_path, "demo.mp3", "自定义字幕")
    assert path.name == "自定义字幕.srt"


def test_reserve_custom_filename_keeps_srt_suffix(tmp_path):
    path = reserve_output_path(tmp_path, "demo.mp3", "custom.srt")
    assert path.name == "custom.srt"


@pytest.mark.parametrize("bad_name", ["../evil.srt", "sub/dir/evil.srt", "", ".srt"])
def test_validate_requested_filename_rejects_invalid(bad_name):
    with pytest.raises(ApiError) as exc_info:
        validate_requested_filename(bad_name)
    assert exc_info.value.code == ErrorCode.INVALID_OUTPUT_FILENAME
