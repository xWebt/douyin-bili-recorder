from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


def _expand_path(value: str | os.PathLike[str], base: Path) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return expanded if expanded.is_absolute() else (base / expanded).resolve()


@dataclass(slots=True)
class TargetConfig:
    name: str
    url: str
    enabled: bool = True
    title_template: str = "{name}｜{start_date} {start_time} 开播"
    tags: list[str] = field(default_factory=list)
    tid: int = 171
    copyright: int = 2
    source: str = ""


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
    keep_original_files: bool
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
    upload = _table(raw, "upload")
    launchd = _table(raw, "launchd", required=False)
    base = config_path.parent

    targets = [_target(item) for item in raw.get("targets", []) if isinstance(item, dict)]
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
        keep_original_files=bool(recording.get("keep_original_files", True)),
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


def _target(raw: dict[str, Any]) -> TargetConfig:
    name = str(raw.get("name", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not name or not url:
        raise ConfigError("Every target requires name and url")
    return TargetConfig(
        name=name,
        url=url,
        enabled=bool(raw.get("enabled", True)),
        title_template=str(raw.get("title_template", "{name}｜{start_date} {start_time} 开播")),
        tags=[str(item) for item in raw.get("tags", [])],
        tid=int(raw.get("tid", 171)),
        copyright=int(raw.get("copyright", 2)),
        source=str(raw.get("source", "")),
    )


def _validate(config: AppConfig) -> None:
    if config.poll_interval_seconds < 5:
        raise ConfigError("poll_interval_seconds must be at least 5")
    if config.max_reconnect_attempts < 0:
        raise ConfigError("max_reconnect_attempts cannot be negative")
    if config.min_file_size_mb < 0:
        raise ConfigError("min_file_size_mb cannot be negative")
    if config.upload_retry_count < 0:
        raise ConfigError("retry_count cannot be negative")
