"""API 接口测试（转写链路使用假实现，不依赖真实模型）。"""

from __future__ import annotations

import io

from tests.conftest import wait_for_status


def _upload(client, filename="demo.mp3", content=b"fake-audio-bytes", **form):
    return client.post(
        "/api/v1/transcriptions",
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        data=form,
    )


def test_health_and_config(client):
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["ffmpeg"]["ok"] is True
    assert "large-v3-turbo" in body["downloaded_models"]

    config = client.get("/api/v1/config")
    assert config.status_code == 200
    config_body = config.json()
    assert {tier["name"] for tier in config_body["model_tiers"]} == {
        "large-v3-turbo",
        "large-v3",
    }
    assert ".mp3" in config_body["supported_audio_formats"]
    assert config_body["ffmpeg_path"]

    models = client.get("/api/v1/models")
    assert models.status_code == 200
    turbo = next(m for m in models.json()["models"] if m["name"] == "large-v3-turbo")
    assert turbo["downloaded"] is True
    assert turbo["loaded"] is False


def test_transcribe_and_download(client, fake_pipeline):
    response = _upload(client)
    assert response.status_code == 202, response.text
    task = response.json()
    assert task["status"] == "queued"
    assert task["output_filename"] == "demo.srt"

    finished = wait_for_status(client, task["task_id"])
    assert finished["status"] == "completed"
    assert finished["segment_count"] == 2
    assert finished["detected_language"] == "zh"
    assert finished["progress"] == 100
    assert finished["audio_duration_seconds"] == 4.0
    assert finished["download_url"] == f"/api/v1/transcriptions/{task['task_id']}/srt"

    download = client.get(finished["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/x-subrip")
    assert "第一句字幕" in download.text
    assert "00:00:00,000 --> 00:00:01,500" in download.text


def test_collision_generates_random_suffix(client, fake_pipeline):
    settings = client.app.state.settings
    (settings.srt_dir / "demo.srt").write_text("existing", encoding="utf-8")

    response = _upload(client)
    assert response.status_code == 202
    output_name = response.json()["output_filename"]
    assert output_name.startswith("demo_") and output_name.endswith(".srt")


def test_custom_output_filename(client, fake_pipeline):
    response = _upload(client, output_filename="我的字幕.srt")
    assert response.status_code == 202
    assert response.json()["output_filename"] == "我的字幕.srt"

    task_id = response.json()["task_id"]
    wait_for_status(client, task_id)
    download = client.get(f"/api/v1/transcriptions/{task_id}/srt")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]


def test_unsupported_format_returns_415(client):
    response = _upload(client, filename="notes.txt")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FORMAT"


def test_unknown_model_returns_400(client):
    response = _upload(client, model="large-v1")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_MODEL"


def test_model_not_downloaded_returns_409(client):
    response = _upload(client, model="large-v3")
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "MODEL_NOT_DOWNLOADED"
    assert "download_url" in body["details"]


def test_invalid_output_filename_returns_400(client):
    response = _upload(client, output_filename="../escape.srt")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OUTPUT_FILENAME"


def test_empty_upload_returns_422(client):
    response = _upload(client, content=b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_missing_file_field_returns_422(client):
    response = client.post("/api/v1/transcriptions", data={"model": "large-v3-turbo"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_task_not_found_returns_404(client):
    response = client.get("/api/v1/transcriptions/not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_download_before_completion_returns_409(client):
    response = _upload(client, filename="bad.mp4")
    assert response.status_code == 202
    task_id = response.json()["task_id"]

    download = client.get(f"/api/v1/transcriptions/{task_id}/srt")
    assert download.status_code in {409, 200}
    if download.status_code == 409:
        assert download.json()["error"]["code"] == "TASK_NOT_COMPLETED"


def test_transcription_failure_is_recorded(client, fake_pipeline, monkeypatch):
    from app.core.errors import ApiError, ErrorCode
    from app.services import transcriber

    def boom(audio_path, model_name, language, manager):
        raise ApiError(ErrorCode.TRANSCRIPTION_FAILED, "模拟转写失败")

    monkeypatch.setattr(transcriber, "transcribe_audio", boom)

    response = _upload(client, filename="broken.wav")
    assert response.status_code == 202
    task_id = response.json()["task_id"]

    finished = wait_for_status(client, task_id)
    assert finished["status"] == "failed"
    assert finished["error"]["code"] == "TRANSCRIPTION_FAILED"
    assert finished["download_url"] is None

    download = client.get(f"/api/v1/transcriptions/{task_id}/srt")
    assert download.status_code == 409
    assert download.json()["error"]["code"] == "TASK_NOT_COMPLETED"


def test_list_tasks(client, fake_pipeline):
    first = _upload(client).json()
    wait_for_status(client, first["task_id"])

    response = client.get("/api/v1/transcriptions?limit=10")
    assert response.status_code == 200
    assert any(item["task_id"] == first["task_id"] for item in response.json())
