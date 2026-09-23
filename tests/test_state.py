from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.models import MediaFile, SessionRecord, SessionStatus
from douyin_bili_recorder.state import SessionStore, SingleInstanceLock


def test_session_store_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = SessionRecord(
        session_id="20260923-201441-anchor",
        target_name="anchor",
        target_url="https://live.douyin.com/123",
        status=SessionStatus.RECORDED,
        created_epoch=1790165681,
        detected_start_epoch=1790165681,
        detected_start_iso="2026-09-23T20:14:41+08:00",
        files=[MediaFile(path="part-000.mp4", size=10, duration_seconds=12.5)],
    )
    store.save(record)
    loaded = store.load(record.session_id)
    assert loaded.session_id == record.session_id
    assert loaded.status == SessionStatus.RECORDED
    assert loaded.files[0].path == "part-000.mp4"
    assert loaded.files[0].duration_seconds == 12.5
