from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.models import SessionPart, SessionRecord
from douyin_bili_recorder.service_control import ServiceController
from douyin_bili_recorder.target_status import TargetStatusStore
from douyin_bili_recorder.ui_state import UIStateStore


def _config(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    return load_config(path)


def test_target_status_store_round_trip(tmp_path: Path) -> None:
    store = TargetStatusStore(_config(tmp_path).data_dir)
    store.update("anchor", "recording", "正在录制直播", session_id="session-1")

    status = store.load_all()["anchor"]
    assert status["state"] == "recording"
    assert status["message"] == "正在录制直播"
    assert status["session_id"] == "session-1"
    assert status["updated_at"] > 0

    store.clear("anchor")
    assert store.load_all() == {}


def test_target_usage_includes_session_and_final_files(tmp_path: Path) -> None:
    config = _config(tmp_path)
    session_dir = config.sessions_dir / "session-1"
    session_dir.mkdir(parents=True)
    (session_dir / "partial.part").write_bytes(b"a" * 10)

    final_media = tmp_path / "final.mp4"
    final_media.write_bytes(b"b" * 20)
    anchor_dir = config.video_dir.expanduser() / "anchor"
    anchor_dir.mkdir(parents=True)
    (anchor_dir / "orphan.mp4").write_bytes(b"c" * 5)
    session = SessionRecord(
        session_id="session-1",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        parts=[
            SessionPart(
                index=1,
                status="UPLOADED",
                path=str(final_media),
                source_path=str(final_media),
            )
        ],
    )

    controller = ServiceController(config, UIStateStore(config))
    usage = controller._target_usage_bytes([session])

    assert usage == {"anchor": 35}


def test_uploaded_artifact_cleanup_keeps_session_json(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, __import__("logging").getLogger("test"))
    session_dir = config.sessions_dir / "session-1"
    runtime_dir = session_dir / ".danmaku-runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "temp.flv").write_bytes(b"a" * 10)
    (session_dir / "session.json").write_text("{}", encoding="utf-8")
    final_media = tmp_path / "final.mp4"
    final_media.write_bytes(b"b" * 20)
    session = SessionRecord(
        session_id="session-1",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status="UPLOADED",
        parts=[SessionPart(index=1, status="UPLOADED", path=str(final_media))],
    )

    service._cleanup_uploaded_artifacts(session)

    assert not final_media.exists()
    assert not runtime_dir.exists()
    assert (session_dir / "session.json").exists()
