from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord, SessionStatus
from douyin_bili_recorder.paths import target_key
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.service_control import ServiceController
from douyin_bili_recorder.ui_state import UIStateStore
from douyin_bili_recorder.uploader import UploadCancelled
from douyin_bili_recorder.webapp import _pause_target


class FakeStateStore:
    def __init__(self) -> None:
        self.state = {
            "targets": [
                {"name": "anchor", "enabled": True},
            ]
        }

    def load(self) -> dict:
        return self.state

    def save(self, state: dict) -> dict:
        self.state = state
        return state

    def render_runtime_config(self, _state: dict) -> None:
        return None


class FakeController:
    def status(self, _limit: int | None = None) -> dict[str, bool]:
        return {"running": True}


class PollingProcess:
    pid = 424242

    @staticmethod
    def poll() -> int:
        return 0


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_pause_target_disables_and_writes_control_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = FakeStateStore()

    result = _pause_target(config, store, FakeController(), "anchor")  # type: ignore[arg-type]

    assert result["enabled"] is False
    assert store.state["targets"][0]["enabled"] is False
    request_path = config.data_dir / "ui" / "target-control" / f"{target_key('anchor')}.request"
    assert request_path.exists()
    assert "pause" in request_path.read_text(encoding="utf-8")


def test_stop_discard_writes_discard_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_store = UIStateStore(config)
    state = state_store.load()
    state["worker_running"] = True
    state_store.save(state)
    controller = ServiceController(config, state_store)

    controller.stop("discard")

    assert controller.stop_request_path.read_text(encoding="utf-8") == "discard"


def test_status_reaps_exited_worker_process(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_store = UIStateStore(config)
    state_store.save_runtime_state({"pid": PollingProcess.pid, "started_at": 1})
    controller = ServiceController(config, state_store)
    controller._process = PollingProcess()  # type: ignore[assignment]

    status = controller.status()

    assert status["running"] is False
    assert status["pid"] is None
    assert state_store.load_runtime_state() == {}


def test_discard_current_session_deletes_files_and_marks_canceled(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part.mp4"
    source = tmp_path / "part.flv"
    media.write_bytes(b"mp4")
    source.write_bytes(b"flv")
    runtime = service.store.session_dir("session") / ".danmaku-runtime"
    runtime.mkdir(parents=True)
    (runtime / "data.bin").write_bytes(b"x")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status=SessionStatus.RECORDING,
        parts=[
            SessionPart(
                index=1,
                status="UPLOADING",
                path=str(media),
                source_path=str(source),
            )
        ],
    )

    service._discard_current_session(config.targets[0], session, [])

    assert not media.exists()
    assert not source.exists()
    assert not runtime.exists()
    saved = service.store.load("session")
    assert saved.status == "CANCELED"
    assert saved.parts[0].status == "CANCELED"
    assert saved.parts[0].path == ""
    assert saved.parts[0].source_path == ""


def test_recorder_stop_reads_discard_request(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    request = tmp_path / "stop.request"
    request.write_text("discard", encoding="utf-8")
    monkeypatch.setenv("DOUYIN_RECORDER_STOP_FILE", str(request))

    service.stop()

    assert service.pause_mode() == "discard"
    assert service.interrupt_event.is_set()


def test_shutdown_stop_preserves_desired_running(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_store = UIStateStore(config)
    state = state_store.load()
    state["worker_running"] = True
    state_store.save(state)
    controller = ServiceController(config, state_store)

    controller.stop("shutdown", persist=False)

    assert state_store.load()["worker_running"] is True
    assert controller.stop_request_path.read_text(encoding="utf-8") == "shutdown"


def test_shutdown_upload_cancellation_keeps_part_pending(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status=SessionStatus.RECORDED,
        parts=[SessionPart(index=1, status="PENDING", title="anchor P01", path=str(media))],
    )
    service.store.save(session)

    class CancelledUploader:
        @staticmethod
        def upload_part(*_args, **_kwargs):
            raise UploadCancelled("shutdown")

    service.uploader = CancelledUploader()  # type: ignore[assignment]
    service.shutdown_event.set()
    result = service._upload_part_with_retries(config.targets[0], session, media, session.parts[0])

    assert not result.verified
    assert service.store.load("session").parts[0].status == "PENDING"
