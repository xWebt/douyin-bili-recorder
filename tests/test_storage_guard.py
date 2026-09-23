from __future__ import annotations

import logging

from douyin_bili_recorder.models import MediaFile, SessionRecord, SessionStatus
from douyin_bili_recorder.state import SessionStore
from douyin_bili_recorder.storage_guard import StorageGuard


def _large_file(path, size: int) -> None:
    with path.open("wb") as handle:
        handle.seek(size - 1)
        handle.write(b"0")


def test_cache_limit_only_removes_uploaded_sessions(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    for session_id, status in (
        ("uploaded", SessionStatus.UPLOADED),
        ("pending", SessionStatus.RECORDED),
    ):
        directory = store.session_dir(session_id)
        media = directory / "part-000.mp4"
        _large_file(media, 600 * 1024 * 1024)
        store.save(
            SessionRecord(
                session_id=session_id,
                target_name=session_id,
                target_url="https://live.douyin.com/1",
                status=status,
                created_epoch=1,
                ended_epoch=1,
                detected_start_epoch=1,
                detected_start_iso="2026-09-23T20:14:41+08:00",
                files=[MediaFile(path="part-000.mp4", size=media.stat().st_size)],
            )
        )

    guard = StorageGuard(sessions_dir, logging.getLogger("test"))
    guard.enforce_limit(1)
    remaining = {session.session_id for session in store.all()}
    assert remaining == {"pending"}
