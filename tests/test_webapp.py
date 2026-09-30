from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.paths import target_key
from douyin_bili_recorder.models import SessionPart, SessionRecord
from douyin_bili_recorder.state import SessionStore
from douyin_bili_recorder.upload_progress import UploadProgressStore
from douyin_bili_recorder.webapp import _ensure_service_running, _request_upload_control, _start_target, _sync_cloud_anchor_folders


class FakeStateStore:
    def load(self) -> dict:
        return {
            "max_cache_gb": 10,
            "targets": [{"name": "anchor", "enabled": False}],
        }

    def save(self, state: dict) -> dict:
        self.state = state
        return state

    def render_runtime_config(self, _state: dict) -> None:
        return None


class FakeController:
    def __init__(self) -> None:
        self.started = False

    def status(self, _limit: int) -> dict[str, bool]:
        return {"running": self.started}

    def start(self) -> dict[str, bool]:
        self.started = True
        return {"running": True}


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_retry_path_starts_stopped_service(tmp_path: Path) -> None:
    config = _config(tmp_path)
    controller = FakeController()

    _ensure_service_running(config, FakeStateStore(), controller)  # type: ignore[arg-type]

    assert controller.started is True


def test_start_target_enables_target_and_queues_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = FakeStateStore()
    controller = FakeController()

    result = _start_target(config, store, controller, "anchor")  # type: ignore[arg-type]

    assert result["enabled"] is True
    assert controller.started is True
    assert (config.data_dir / "ui" / "manual" / f"{target_key('anchor')}.request").exists()


def test_sync_cloud_anchor_folders_creates_configured_anchor(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr("douyin_bili_recorder.webapp.subprocess.run", fake_run)
    current = {
        "cloud_rclone_bin": "rclone",
        "targets": [
            {
                "id": "anchor-id",
                "name": "凡晨",
                "cloud_backup": False,
                "cloud_remote": "quark:/DouyinBiliRecorder",
            }
        ],
    }

    folders, warnings = _sync_cloud_anchor_folders(config, current)

    assert warnings == []
    assert folders == ["quark:/DouyinBiliRecorder/凡晨"]
    assert calls[-1][-1] == "quark:/DouyinBiliRecorder/凡晨"


def test_sync_cloud_anchor_folders_skips_anchor_without_remote(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr("douyin_bili_recorder.webapp.subprocess.run", fake_run)
    target = {
        "id": "anchor-id",
        "name": "凡晨",
        "cloud_backup": False,
        "cloud_remote": "",
    }

    folders, warnings = _sync_cloud_anchor_folders(config, {"targets": [target]})

    assert folders == []
    assert warnings == []
    assert calls == []


def test_delete_upload_control_removes_local_media(tmp_path: Path) -> None:
    config = _config(tmp_path)
    video_dir = tmp_path / "videos"
    config.video_dir = video_dir
    video_dir.mkdir()
    media = video_dir / "part.flv"
    danmaku = video_dir / "part.xml"
    media.write_bytes(b"video")
    danmaku.write_text("<i />", encoding="utf-8")
    session = SessionRecord(
        session_id="delete-session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        parts=[
            SessionPart(
                index=1,
                status="UPLOADING",
                path=str(media),
                danmaku_path=str(danmaku),
            )
        ],
    )
    SessionStore(config.sessions_dir).save(session)

    result = _request_upload_control(config, session.session_id, 1, "delete")

    assert result["ok"] is True
    assert not media.exists()
    assert not danmaku.exists()
    saved = SessionStore(config.sessions_dir).load(session.session_id)
    assert saved.status == "CANCELED"
    assert saved.parts[0].path == ""
    assert saved.parts[0].danmaku_path == ""
    progress = UploadProgressStore(config.data_dir).load()
    assert progress["available"] is False
    request = config.data_dir / "ui" / "upload-control" / f"{session.session_id}-1.request"
    assert '"action": "delete"' in request.read_text(encoding="utf-8")
