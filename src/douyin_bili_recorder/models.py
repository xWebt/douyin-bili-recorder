from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SessionStatus(StrEnum):
    STARTING = "STARTING"
    RECORDING = "RECORDING"
    RECORDED = "RECORDED"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    UPLOAD_SUBMITTED_UNVERIFIED = "UPLOAD_SUBMITTED_UNVERIFIED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    FAILED = "FAILED"


@dataclass(slots=True)
class ScheduleSlot:
    days: list[int]
    start: str
    end: str
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleSlot:
        days = [int(day) for day in data.get("days", []) if str(day).isdigit()]
        return cls(
            days=[day for day in days if 1 <= day <= 7],
            start=str(data.get("start", "20:00")),
            end=str(data.get("end", "23:00")),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "days": list(self.days),
            "start": self.start,
            "end": self.end,
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class MediaFile:
    path: str
    size: int
    duration_seconds: float | None = None
    sha256: str | None = None
    source: str | None = None
    uploaded: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MediaFile:
        return cls(
            path=str(data["path"]),
            size=int(data.get("size", 0)),
            duration_seconds=data.get("duration_seconds"),
            sha256=data.get("sha256"),
            source=data.get("source"),
            uploaded=bool(data.get("uploaded", False)),
        )


@dataclass(slots=True)
class SessionPart:
    index: int
    status: str = "PENDING"
    title: str = ""
    path: str = ""
    source_path: str = ""
    size: int = 0
    duration_seconds: float | None = None
    bvid: str | None = None
    uploaded_at: int | None = None
    error: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionPart:
        return cls(
            index=int(data.get("index", 0)),
            status=str(data.get("status", "PENDING")),
            title=str(data.get("title", "")),
            path=str(data.get("path", "")),
            source_path=str(data.get("source_path", "")),
            size=int(data.get("size", 0)),
            duration_seconds=data.get("duration_seconds"),
            bvid=data.get("bvid"),
            uploaded_at=data.get("uploaded_at"),
            error=str(data.get("error", "")),
        )


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    target_name: str
    target_url: str
    status: str = SessionStatus.STARTING
    created_epoch: int = 0
    detected_start_epoch: int | None = None
    detected_start_iso: str | None = None
    ended_epoch: int | None = None
    room_title: str = ""
    bvid: str | None = None
    title: str = ""
    attempts: int = 0
    error: str = ""
    files: list[MediaFile] = field(default_factory=list)
    parts: list[SessionPart] = field(default_factory=list)
    record_mode: str = "record"
    scheduled_start_epoch: int | None = None
    late: bool = False
    late_minutes: int = 0
    last_seen_live_epoch: int | None = None
    reconnect_count: int = 0
    reconnect_seconds: int = 0
    collection_id: str = ""
    collection_status: str = ""

    @property
    def directory_name(self) -> str:
        return self.session_id

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["files"] = [asdict(item) for item in self.files]
        result["parts"] = [asdict(item) for item in self.parts]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionRecord:
        return cls(
            session_id=str(data["session_id"]),
            target_name=str(data["target_name"]),
            target_url=str(data["target_url"]),
            status=str(data.get("status", SessionStatus.STARTING)),
            created_epoch=int(data.get("created_epoch", 0)),
            detected_start_epoch=data.get("detected_start_epoch"),
            detected_start_iso=data.get("detected_start_iso"),
            ended_epoch=data.get("ended_epoch"),
            room_title=str(data.get("room_title", "")),
            bvid=data.get("bvid"),
            title=str(data.get("title", "")),
            attempts=int(data.get("attempts", 0)),
            error=str(data.get("error", "")),
            files=[MediaFile.from_dict(item) for item in data.get("files", [])],
            parts=[SessionPart.from_dict(item) for item in data.get("parts", [])],
            record_mode=str(data.get("record_mode", "record")),
            scheduled_start_epoch=data.get("scheduled_start_epoch"),
            late=bool(data.get("late", False)),
            late_minutes=int(data.get("late_minutes", 0)),
            last_seen_live_epoch=data.get("last_seen_live_epoch"),
            reconnect_count=int(data.get("reconnect_count", 0)),
            reconnect_seconds=int(data.get("reconnect_seconds", 0)),
            collection_id=str(data.get("collection_id", "")),
            collection_status=str(data.get("collection_status", "")),
        )

    def media_paths(self, root: Path) -> list[Path]:
        return [root / item.path for item in self.files]
