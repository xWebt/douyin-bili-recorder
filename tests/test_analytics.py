from __future__ import annotations

import json
from pathlib import Path

from douyin_bili_recorder.analytics import AnalyticsStore
from douyin_bili_recorder.models import SessionPart, SessionRecord, SessionStatus


def test_analytics_ignores_offline_poll_without_media(tmp_path: Path) -> None:
    analytics_path = tmp_path / "anchor" / "直播数据" / "2026-09.json"
    analytics_path.parent.mkdir(parents=True)
    analytics_path.write_text(
        json.dumps(
            {
                "version": 1,
                "month": "2026-09",
                "target_name": "anchor",
                "sessions": [
                    {
                        "session_id": "offline-poll",
                        "date": "2026-09-25",
                        "mode": "record",
                        "detected_start_iso": "2026-09-25T00:21:33+08:00",
                        "parts": 0,
                        "bvid": None,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = AnalyticsStore(tmp_path, "Asia/Shanghai")
    valid = SessionRecord(
        session_id="real",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        detected_start_epoch=1,
        detected_start_iso="2026-09-25T00:52:39+08:00",
        ended_epoch=2,
        parts=[SessionPart(index=1, status="UPLOADED", path="/tmp/a.mp4")],
    )
    store.upsert(valid)
    summary = store.summary("anchor", "2026-09")
    assert summary["sessions"] == 1
    assert summary["sessions_detail"][0]["session_id"] == "real"


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
