"""测试夹具：用临时目录隔离数据，并注入假的模型与转写实现（无需真实模型/torch）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    # 用占位文件模拟"已下载"的极速版模型
    (model_dir / "large-v3-turbo.pt").write_bytes(b"fake-model")

    monkeypatch.setenv("AUDIO2SRT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AUDIO2SRT_MODEL_DIR", str(model_dir))
    monkeypatch.delenv("AUDIO2SRT_KEEP_UPLOADS", raising=False)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("FFPROBE_PATH", raising=False)

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


@pytest.fixture
def fake_pipeline(monkeypatch):
    """把 ffmpeg 转码与 whisper 转写替换成确定性的假实现。"""

    def fake_normalize(input_path, output_path):
        output_path.write_bytes(b"RIFF")

    def fake_probe(path):
        return 4.0

    def fake_transcribe(audio_path, model_name, language, manager):
        return {
            "segments": [
                {"start": 0.0, "end": 1.5, "text": "第一句字幕"},
                {"start": 1.5, "end": 4.0, "text": "第二句字幕"},
            ],
            "language": "zh",
            "duration": 4.0,
        }

    from app.core import ffmpeg
    from app.services import transcriber

    monkeypatch.setattr(ffmpeg, "normalize_audio", fake_normalize)
    monkeypatch.setattr(ffmpeg, "probe_duration", fake_probe)
    monkeypatch.setattr(transcriber, "transcribe_audio", fake_transcribe)


def wait_for_status(client, task_id, timeout=3.0):
    """轮询直到任务进入终态。"""
    import time

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/v1/transcriptions/{task_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in {"completed", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内完成: {last}")
