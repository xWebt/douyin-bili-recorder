from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord, SessionStatus
from douyin_bili_recorder.paths import target_key
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.service_control import ServiceController
from douyin_bili_recorder.ui_state import UIStateStore
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


def test_discard_current_session_deletes_files_and_marks_canceled(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part.mp4"
    source = tmp_path / "part.flv"
    media.write_bytes(b"mp4")
    source.write_bytes(b"flv")
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
    saved = service.store.load("session")
    assert saved.status == "CANCELED"
    assert saved.parts[0].status == "CANCELED"
    assert saved.parts[0].path == ""
    assert saved.parts[0].source_path == ""
