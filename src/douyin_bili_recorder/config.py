from __future__ import annotations

import os
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ScheduleSlot


class ConfigError(ValueError):
    pass


def resolve_executable(name: str, config_dir: Path) -> str:
    candidate = Path(os.path.expanduser(name))
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)

    venv_candidate = Path(sys.executable).parent / name
    if venv_candidate.exists():
        return str(venv_candidate)

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for bundle_dir in (bundle_root / "bin", Path(sys.executable).parent / "bin"):
        bundled_candidate = bundle_dir / name
        if bundled_candidate.exists():
            return str(bundled_candidate)

    project_candidate = config_dir / ".tools" / "ffmpeg" / name
    if project_candidate.exists():
        return str(project_candidate)

    return shutil.which(name) or name


def _expand_path(value: str | os.PathLike[str], base: Path) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return expanded if expanded.is_absolute() else (base / expanded).resolve()


@dataclass(slots=True)
class TargetConfig:
    name: str
    url: str
    enabled: bool = True
    public: bool = False
    record_mode: str = "record"
    collection_name: str = ""
    collection_id: str = ""
    title_template: str = "{name}｜{start_date} {start_time} 开播｜{room_title}"
    tags: list[str] = field(default_factory=list)
    tid: int = 171
    copyright: int = 2
    source: str = ""
    schedule: list[ScheduleSlot] = field(default_factory=list)


@dataclass(slots=True)
class AppConfig:
    name: str
    timezone: str
    data_dir: Path
    poll_interval_seconds: int
    max_reconnect_attempts: int
    reconnect_backoff_seconds: int
    segment_time: str
    min_file_size_mb: int
    max_cache_gb: int
    keep_original_files: bool
    video_dir: Path
    late_threshold_minutes: int
    reconnect_grace_minutes: int
    biliup_bin: str
    ffmpeg_bin: str
    ffprobe_bin: str
    cookie_file: Path
    upload_line: str
    public: bool
    delete_after_upload: bool
    upload_retry_count: int
    upload_retry_backoff_seconds: int
    launchd_label: str
    targets: list[TargetConfig]
    config_path: Path

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    app = _table(raw, "app")
    recording = _table(raw, "recording")
    storage = _table(raw, "storage", required=False)
    upload = _table(raw, "upload")
    launchd = _table(raw, "launchd", required=False)
    base = config_path.parent

    default_public = bool(upload.get("public", False))
    targets = [
        _target(item, default_public=default_public)
        for item in raw.get("targets", [])
        if isinstance(item, dict)
    ]
    if not targets:
        raise ConfigError("At least one [[targets]] entry is required")

    names = [target.name for target in targets]
    if len(names) != len(set(names)):
        raise ConfigError("Target names must be unique")

    config = AppConfig(
        name=str(app.get("name", "douyin-bili-recorder")),
        timezone=str(app.get("timezone", "Asia/Shanghai")),
        data_dir=_expand_path(app.get("data_dir", "data"), base),
        poll_interval_seconds=int(app.get("poll_interval_seconds", 30)),
        max_reconnect_attempts=int(app.get("max_reconnect_attempts", 5)),
        reconnect_backoff_seconds=int(app.get("reconnect_backoff_seconds", 15)),
        segment_time=str(recording.get("segment_time", "1h")),
        min_file_size_mb=int(recording.get("min_file_size_mb", 10)),
        max_cache_gb=int(storage.get("max_cache_gb", 10)),
        keep_original_files=bool(recording.get("keep_original_files", True)),
        video_dir=_expand_path(
            storage.get("video_dir", "~/Movies/DouyinBiliRecorder"),
            base,
        ),
        late_threshold_minutes=int(storage.get("late_threshold_minutes", 5)),
        reconnect_grace_minutes=int(storage.get("reconnect_grace_minutes", 15)),
        biliup_bin=str(upload.get("biliup_bin", "biliup")),
        ffmpeg_bin=str(upload.get("ffmpeg_bin", "ffmpeg")),
        ffprobe_bin=str(upload.get("ffprobe_bin", "ffprobe")),
        cookie_file=_expand_path(upload.get("cookie_file", "cookies.json"), base),
        upload_line=str(upload.get("line", "bda2")),
        public=bool(upload.get("public", False)),
        delete_after_upload=bool(upload.get("delete_after_upload", False)),
        upload_retry_count=int(upload.get("retry_count", 5)),
        upload_retry_backoff_seconds=int(upload.get("retry_backoff_seconds", 30)),
        launchd_label=str(launchd.get("label", "com.webt.douyin-bili-recorder")),
        targets=targets,
        config_path=config_path,
    )
    _validate(config)
    return config


def _table(raw: dict[str, Any], name: str, *, required: bool = True) -> dict[str, Any]:
    value = raw.get(name, {})
    if isinstance(value, dict):
        return value
    if required:
        raise ConfigError(f"[{name}] must be a TOML table")
    return {}


def _target(raw: dict[str, Any], *, default_public: bool = False) -> TargetConfig:
    name = str(raw.get("name", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not name or not url:
        raise ConfigError("Every target requires name and url")
    return TargetConfig(
        name=name,
        url=url,
        enabled=bool(raw.get("enabled", True)),
        public=bool(raw.get("public", default_public)),
        record_mode=str(raw.get("record_mode", "record")),
        collection_name=str(raw.get("collection_name", "")),
        collection_id=str(raw.get("collection_id", "")),
        title_template=str(raw.get("title_template", "{name}｜{start_date} {start_time} 开播｜{room_title}")),
        tags=[str(item) for item in raw.get("tags", [])],
        tid=int(raw.get("tid", 171)),
        copyright=int(raw.get("copyright", 2)),
        source=str(raw.get("source", "")),
        schedule=[
            ScheduleSlot.from_dict(item)
            for item in raw.get("schedule", [])
            if isinstance(item, dict)
        ],
    )


def _validate(config: AppConfig) -> None:
    if config.poll_interval_seconds < 5:
        raise ConfigError("poll_interval_seconds must be at least 5")
    if config.max_reconnect_attempts < 0:
        raise ConfigError("max_reconnect_attempts cannot be negative")
    if config.min_file_size_mb < 0:
        raise ConfigError("min_file_size_mb cannot be negative")
    if config.max_cache_gb < 1:
        raise ConfigError("max_cache_gb must be at least 1")
    if config.late_threshold_minutes < 0:
        raise ConfigError("late_threshold_minutes cannot be negative")
    if config.reconnect_grace_minutes < 0:
        raise ConfigError("reconnect_grace_minutes cannot be negative")
    if config.upload_retry_count < 0:
        raise ConfigError("retry_count cannot be negative")
    for target in config.targets:
        if target.record_mode not in {"record", "monitor"}:
            raise ConfigError(f"target {target.name} has invalid record_mode: {target.record_mode}")
