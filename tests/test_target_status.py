from __future__ import annotations

import time
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.models import SessionPart, SessionRecord
from douyin_bili_recorder.paths import session_output_dir
from douyin_bili_recorder.service_control import ServiceController
from douyin_bili_recorder.target_status import TargetStatusStore
from douyin_bili_recorder.ui_state import UIStateStore
from douyin_bili_recorder.upload_progress import UploadProgressStore


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


def test_status_removes_deleted_upload_progress(tmp_path: Path) -> None:
    config = _config(tmp_path)
    progress = UploadProgressStore(config.data_dir)
    progress.upsert(
        "live:1",
        {"available": True, "target": "anchor", "percent": 50, "updated_at": "2026-09-30T01:00:00"},
    )
    progress.upsert(
        "deleted:1",
        {
            "available": False,
            "state": "deleted",
            "target": "anchor",
            "percent": 99.9,
            "updated_at": "2026-09-30T01:00:01",
        },
    )

    status = ServiceController(config, UIStateStore(config)).status()

    assert [item["key"] for item in status["upload_progresses"]] == ["live:1"]
    assert [item["key"] for item in progress.load_all()] == ["live:1"]


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
    usage = controller._target_usage_bytes([session], ["anchor"])

    assert usage == {"anchor": 35}


def test_orphan_completed_part_is_restored_to_recent_session(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, __import__("logging").getLogger("test"))
    start_epoch = int(time.time()) - 3600
    session = SessionRecord(
        session_id="session-1",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status="UPLOADED",
        created_epoch=start_epoch,
        detected_start_epoch=start_epoch,
        room_title="直播录像",
        title="anchor｜直播",
        bvid="BV0000000001",
        parts=[SessionPart(index=1, status="UPLOADED", path=str(tmp_path / "missing-p01.mp4"))],
    )
    output_dir = session_output_dir(
        config.video_dir,
        "anchor",
        start_epoch,
        config.timezone,
        "直播录像",
        session.session_id,
    )
    output_dir.mkdir(parents=True)
    media = output_dir / "1200_直播录像_P02.mp4"
    media.write_bytes(b"video")
    media.with_suffix(".flv").write_bytes(b"source")
    media.with_suffix(".xml").write_text("<i/>", encoding="utf-8")

    service._recover_orphan_parts(session, config.targets[0])

    assert [part.index for part in session.parts] == [1, 2]
    assert session.parts[1].status == "PENDING"
    assert session.parts[1].path == str(media)
    assert session.status == "RECORDED"


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
