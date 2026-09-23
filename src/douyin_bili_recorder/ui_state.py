from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import AppConfig, resolve_executable


def _target_id() -> str:
    return uuid.uuid4().hex[:10]


def _default_state(config: AppConfig) -> dict[str, Any]:
    return {
        "version": 2,
        "public": config.public,
        "max_cache_gb": config.max_cache_gb,
        "delete_after_upload": config.delete_after_upload,
        "auto_restart": True,
        "worker_running": False,
        "poll_interval_seconds": config.poll_interval_seconds,
        "video_dir": str(config.video_dir),
        "late_threshold_minutes": config.late_threshold_minutes,
        "reconnect_grace_minutes": config.reconnect_grace_minutes,
        "targets": [
            {
                "id": _target_id(),
                "name": target.name,
                "url": target.url,
                "enabled": target.enabled,
                "public": target.public,
                "record_mode": target.record_mode,
                "watch_mode": target.watch_mode,
                "collection_name": target.collection_name,
                "collection_id": target.collection_id,
                "title_template": target.title_template,
                "tags": list(target.tags),
                "tid": target.tid,
                "copyright": target.copyright,
                "source": target.source,
                "schedule": [slot.to_dict() for slot in target.schedule],
            }
            for target in config.targets
        ],
    }


class UIStateStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.root = config.data_dir / "ui"
        self.state_path = self.root / "state.json"
        self.runtime_config_path = self.root / "runtime-config.toml"
        self.runtime_state_path = self.root / "runtime.json"
        self.worker_log_path = config.logs_dir / "ui-worker.log"

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            state = _default_state(self.config)
            self.save(state)
            return state
        with self.state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        return self._normalize(state)

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(state)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(normalized, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=".ui-state-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return normalized

    def render_runtime_config(self, state: dict[str, Any]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        public = bool(state.get("public", self.config.public))
        config_dir = self.config.config_path.parent
        biliup_bin = (
            "__INTERNAL_BILIUP__"
            if getattr(sys, "frozen", False)
            else resolve_executable(self.config.biliup_bin, config_dir)
        )
        ffmpeg_bin = resolve_executable(self.config.ffmpeg_bin, config_dir)
        ffprobe_bin = resolve_executable(self.config.ffprobe_bin, config_dir)
        lines = [
            "[app]",
            f'name = {json.dumps(self.config.name, ensure_ascii=False)}',
            f'timezone = {json.dumps(self.config.timezone)}',
            f'data_dir = {json.dumps(str(self.config.data_dir))}',
            f"poll_interval_seconds = {int(state.get('poll_interval_seconds', self.config.poll_interval_seconds))}",
            f"max_reconnect_attempts = {self.config.max_reconnect_attempts}",
            f"reconnect_backoff_seconds = {self.config.reconnect_backoff_seconds}",
            "",
            "[recording]",
            f'segment_time = {json.dumps(self.config.segment_time)}',
            f"min_file_size_mb = {self.config.min_file_size_mb}",
            f"keep_original_files = {str(self.config.keep_original_files).lower()}",
            "",
            "[storage]",
            f"max_cache_gb = {int(state.get('max_cache_gb', self.config.max_cache_gb))}",
            f'video_dir = {json.dumps(str(state.get("video_dir", self.config.video_dir)))}',
            f"late_threshold_minutes = {int(state.get('late_threshold_minutes', self.config.late_threshold_minutes))}",
            f"reconnect_grace_minutes = {int(state.get('reconnect_grace_minutes', self.config.reconnect_grace_minutes))}",
            "",
            "[upload]",
            f'biliup_bin = {json.dumps(biliup_bin)}',
            f'ffmpeg_bin = {json.dumps(ffmpeg_bin)}',
            f'ffprobe_bin = {json.dumps(ffprobe_bin)}',
            f'cookie_file = {json.dumps(str(self.config.cookie_file))}',
            f'line = {json.dumps(self.config.upload_line)}',
            f"public = {str(public).lower()}",
            f"delete_after_upload = {str(bool(state.get('delete_after_upload', self.config.delete_after_upload))).lower()}",
            f"retry_count = {self.config.upload_retry_count}",
            f"retry_backoff_seconds = {self.config.upload_retry_backoff_seconds}",
            "",
            "[launchd]",
            f'label = {json.dumps(self.config.launchd_label)}',
        ]
        for target in state.get("targets", []):
            lines.extend(
                [
                    "",
                    "[[targets]]",
                    f'name = {json.dumps(str(target["name"]), ensure_ascii=False)}',
                    f'url = {json.dumps(str(target["url"]))}',
                    f"enabled = {str(bool(target.get('enabled', True))).lower()}",
                    f"public = {str(bool(target.get('public', public))).lower()}",
                    f"record_mode = {json.dumps(str(target.get('record_mode', 'record')))}",
                    f"watch_mode = {json.dumps(str(target.get('watch_mode', 'scheduled')))}",
                    f"collection_name = {json.dumps(str(target.get('collection_name', '')), ensure_ascii=False)}",
                    f"collection_id = {json.dumps(str(target.get('collection_id', '')))}",
                    f"title_template = {json.dumps(str(target.get('title_template') or '{name}｜{start_date} {start_time} 开播｜{room_title}'), ensure_ascii=False)}",
                    f"tags = {json.dumps(target.get('tags') or ['直播录像', '抖音'], ensure_ascii=False)}",
                    f"tid = {int(target.get('tid', 171))}",
                    f"copyright = {int(target.get('copyright', 2))}",
                    f'source = {json.dumps(str(target.get("source", "")), ensure_ascii=False)}',
                ]
            )
            schedule = target.get("schedule") or []
            for slot in schedule:
                if not isinstance(slot, dict):
                    continue
                lines.extend(
                    [
                        "",
                        "[[targets.schedule]]",
                        f"days = {json.dumps([int(day) for day in slot.get('days', []) if 1 <= int(day) <= 7])}",
                        f"start = {json.dumps(str(slot.get('start', '20:00')))}",
                        f"end = {json.dumps(str(slot.get('end', '23:00')))}",
                        f"enabled = {str(bool(slot.get('enabled', True))).lower()}",
                    ]
                )
        self.runtime_config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.runtime_config_path

    def save_runtime_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime_state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_runtime_state(self) -> dict[str, Any]:
        if not self.runtime_state_path.exists():
            return {}
        try:
            return json.loads(self.runtime_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _normalize(self, state: dict[str, Any]) -> dict[str, Any]:
        targets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in state.get("targets", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            if not name or not url:
                continue
            target_id = str(item.get("id") or _target_id())
            if target_id in seen:
                target_id = _target_id()
            seen.add(target_id)
            target_schedule = []
            for slot in item.get("schedule", []):
                if not isinstance(slot, dict):
                    continue
                days = []
                for day in slot.get("days", []):
                    try:
                        value = int(day)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= value <= 7 and value not in days:
                        days.append(value)
                target_schedule.append(
                    {
                        "days": sorted(days),
                        "start": str(slot.get("start", "20:00")),
                        "end": str(slot.get("end", "23:00")),
                        "enabled": bool(slot.get("enabled", True)),
                    }
                )
            targets.append(
                {
                    "id": target_id,
                    "name": name,
                    "url": url,
                    "enabled": bool(item.get("enabled", True)),
                    "public": bool(item.get("public", state.get("public", self.config.public))),
                    "record_mode": (
                        str(item.get("record_mode", "record"))
                        if str(item.get("record_mode", "record")) in {"record", "monitor"}
                        else "record"
                    ),
                    "watch_mode": (
                        str(item.get("watch_mode", "all_day"))
                        if str(item.get("watch_mode", "all_day")) in {"scheduled", "all_day", "manual"}
                        else "all_day"
                    ),
                    "collection_name": str(item.get("collection_name", name)),
                    "collection_id": str(item.get("collection_id", "")),
                    "title_template": str(
                        item.get("title_template")
                        or "{name}｜{start_date} {start_time} 开播｜{room_title}"
                    ),
                    "tags": [str(tag) for tag in item.get("tags", ["直播录像", "抖音"])],
                    "tid": int(item.get("tid", 171)),
                    "copyright": int(item.get("copyright", 2)),
                    "source": str(item.get("source", "")),
                    "schedule": target_schedule,
                }
            )
        return {
            "version": 2,
            "public": bool(state.get("public", self.config.public)),
            "max_cache_gb": max(1, int(state.get("max_cache_gb", self.config.max_cache_gb))),
            "delete_after_upload": bool(state.get("delete_after_upload", self.config.delete_after_upload)),
            "auto_restart": bool(state.get("auto_restart", True)),
            "worker_running": bool(state.get("worker_running", False)),
            "poll_interval_seconds": max(
                5,
                int(state.get("poll_interval_seconds", self.config.poll_interval_seconds)),
            ),
            "video_dir": str(state.get("video_dir", self.config.video_dir)),
            "late_threshold_minutes": max(
                0,
                int(state.get("late_threshold_minutes", self.config.late_threshold_minutes)),
            ),
            "reconnect_grace_minutes": max(
                0,
                int(state.get("reconnect_grace_minutes", self.config.reconnect_grace_minutes)),
            ),
            "targets": targets,
        }

    def clone(self, state: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(self._normalize(state))
