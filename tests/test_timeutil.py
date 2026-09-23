from __future__ import annotations

from douyin_bili_recorder.models import SessionRecord
from douyin_bili_recorder.timeutil import build_title


def test_build_title_uses_detected_start() -> None:
    session = SessionRecord(
        session_id="s1",
        target_name="anchor",
        target_url="https://example.test/live",
        detected_start_epoch=1790165681,
        detected_start_iso="2026-09-23T20:14:41+08:00",
        created_epoch=1790165680,
    )
    title = build_title(
        "{name}｜{start_date} {start_time} 开播｜{room_title}",
        "anchor",
        session.target_url,
        session,
        "Asia/Shanghai",
    )
    assert title == "anchor｜2026-09-23 20:14 开播"
