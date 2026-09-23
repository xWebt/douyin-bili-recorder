from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.analytics import AnalyticsStore
from douyin_bili_recorder.models import SessionPart, SessionRecord, SessionStatus


def test_analytics_counts_late_days_and_sessions(tmp_path: Path) -> None:
    store = AnalyticsStore(tmp_path, "Asia/Shanghai")
    for session_id, start, late, minutes in (
        ("one", "2026-09-23T20:06:00+08:00", True, 6),
        ("two", "2026-09-23T23:10:00+08:00", True, 10),
    ):
        session = SessionRecord(
            session_id=session_id,
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.RECORDED,
            detected_start_epoch=1,
            detected_start_iso=start,
            ended_epoch=2,
            late=late,
            late_minutes=minutes,
            parts=[SessionPart(index=1, status="UPLOADED", path="/tmp/a.mp4")],
        )
        store.upsert(session)

    summary = store.summary("anchor", "2026-09")
    assert summary["live_days"] == 1
    assert summary["sessions"] == 2
    assert summary["late_days"] == 1
    assert summary["late_sessions"] == 2
    assert (tmp_path / "anchor" / "直播数据" / "2026-09.json").exists()
