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

    @property
    def directory_name(self) -> str:
        return self.session_id

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["files"] = [asdict(item) for item in self.files]
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
        )

    def media_paths(self, root: Path) -> list[Path]:
        return [root / item.path for item in self.files]
