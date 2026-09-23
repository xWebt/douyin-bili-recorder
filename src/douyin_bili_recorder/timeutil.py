from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .models import SessionRecord


def now_in_timezone(timezone: str) -> datetime:
    return datetime.now(ZoneInfo(timezone))


def epoch_iso(epoch: int, timezone: str) -> str:
    return datetime.fromtimestamp(epoch, ZoneInfo(timezone)).isoformat(timespec="seconds")


def build_title(template: str, target_name: str, target_url: str, session: SessionRecord, timezone: str) -> str:
    start_epoch = session.detected_start_epoch or session.created_epoch
    start = datetime.fromtimestamp(start_epoch, ZoneInfo(timezone))
    values = {
        "name": target_name,
        "url": target_url,
        "room_title": session.room_title or "",
        "start_epoch": str(start_epoch),
        "start_iso": start.isoformat(timespec="seconds"),
        "start_date": start.strftime("%Y-%m-%d"),
        "start_time": start.strftime("%H:%M"),
    }
    title = template.format_map(values).strip()
    title = title.strip().strip("｜|").strip()
    return " ".join(title.split())
