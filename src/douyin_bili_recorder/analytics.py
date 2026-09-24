from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .models import SessionRecord
from .paths import analytics_dir


class AnalyticsStore:
    def __init__(self, video_dir: Path, timezone: str = "Asia/Shanghai") -> None:
        self.video_dir = video_dir
        self.timezone = timezone

    def upsert(self, session: SessionRecord) -> None:
        if not session.detected_start_iso:
            return
        month = session.detected_start_iso[:7]
        path = analytics_dir(self.video_dir, session.target_name) / f"{month}.json"
        document = self._load(path, month=month, target_name=session.target_name)
        records = [
            item
            for item in document.get("sessions", [])
            if item.get("session_id") != session.session_id and self._record_is_countable(item)
        ]
        if self._session_is_countable(session):
            records.append(self._record(session))
        document["sessions"] = sorted(records, key=lambda item: (item.get("date", ""), item.get("session_id", "")))
        self._write(path, document)
        self._write_summary(session.target_name)

    def month(self, target_name: str, month: str) -> dict[str, Any]:
        path = analytics_dir(self.video_dir, target_name) / f"{month}.json"
        return self._load(path, month=month, target_name=target_name)

    def summary(self, target_name: str, month: str) -> dict[str, Any]:
        document = self.month(target_name, month)
        sessions = [item for item in document.get("sessions", []) if isinstance(item, dict)]
        sessions = [item for item in sessions if self._record_is_countable(item)]
        live_dates = {str(item.get("date")) for item in sessions if item.get("date")}
        late_items = [item for item in sessions if item.get("late")]
        late_dates = {str(item.get("date")) for item in late_items if item.get("date")}
        durations = [int(item.get("duration_seconds") or 0) for item in sessions]
        return {
            "month": month,
            "live_days": len(live_dates),
            "sessions": len(sessions),
            "late_days": len(late_dates),
            "late_sessions": len(late_items),
            "total_duration_seconds": sum(durations),
            "average_duration_seconds": round(sum(durations) / len(durations)) if durations else 0,
            "on_time_rate": round((len(sessions) - len(late_items)) / len(sessions) * 100, 1) if sessions else 100.0,
            "sessions_detail": sessions,
        }

    @staticmethod
    def _session_is_countable(session: SessionRecord) -> bool:
        if session.record_mode == "monitor":
            return True
        return bool(session.parts or session.files or session.bvid)

    @staticmethod
    def _record_is_countable(item: dict[str, Any]) -> bool:
        if item.get("mode") == "monitor":
            return True
        try:
            parts = int(item.get("parts", 0) or 0)
        except (TypeError, ValueError):
            parts = 0
        return bool(parts or item.get("bvid"))

    def _record(self, session: SessionRecord) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "date": (session.detected_start_iso or "")[:10],
            "target_name": session.target_name,
            "status": session.status,
            "mode": session.record_mode,
            "scheduled_start_iso": None
            if session.scheduled_start_epoch is None
            else datetime.fromtimestamp(session.scheduled_start_epoch, ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
            "detected_start_iso": session.detected_start_iso,
            "ended_iso": None
            if session.ended_epoch is None
            else datetime.fromtimestamp(session.ended_epoch, ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
            "duration_seconds": max(0, int((session.ended_epoch or session.detected_start_epoch or 0) - (session.detected_start_epoch or 0))),
            "late": bool(session.late),
            "late_minutes": int(session.late_minutes),
            "reconnect_count": int(session.reconnect_count),
            "reconnect_seconds": int(session.reconnect_seconds),
            "bvid": session.bvid,
            "collection_id": session.collection_id,
            "collection_status": session.collection_status,
            "parts": len(session.parts),
            "title": session.title,
            "room_title": session.room_title,
        }

    def _load(self, path: Path, *, month: str, target_name: str) -> dict[str, Any]:
        if not path.exists():
            return {"version": 1, "month": month, "target_name": target_name, "sessions": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "month": month, "target_name": target_name, "sessions": []}
        if not isinstance(payload, dict):
            return {"version": 1, "month": month, "target_name": target_name, "sessions": []}
        return payload

    def _write(self, path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".analytics-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _write_summary(self, target_name: str) -> None:
        root = analytics_dir(self.video_dir, target_name)
        months = sorted(path.stem for path in root.glob("????-??.json"))
        summaries = [self.summary(target_name, month) for month in months]
        payload = {"version": 1, "target_name": target_name, "months": summaries}
        self._write(root / "汇总.json", payload)
