from __future__ import annotations

import re
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


INVALID_PATH_CHARS = re.compile(r"[\x00-\x1f/:\\]+")


def safe_path_name(value: str, fallback: str = "未命名") -> str:
    cleaned = INVALID_PATH_CHARS.sub("_", value).strip().strip(".")
    cleaned = " ".join(cleaned.split())
    return cleaned[:120] or fallback


def anchor_dir(video_dir: Path, anchor_name: str) -> Path:
    return video_dir / safe_path_name(anchor_name, "未命名主播")


def session_output_dir(
    video_dir: Path,
    anchor_name: str,
    detected_start_epoch: int,
    timezone: str,
    room_title: str = "",
    session_id: str = "",
) -> Path:
    started = datetime.fromtimestamp(detected_start_epoch, ZoneInfo(timezone))
    title = safe_path_name(room_title or "直播录像", "直播录像")
    leaf = f"{started.strftime('%H%M')}_{title}"
    if session_id:
        leaf = f"{leaf}_{session_id.rsplit('-', 1)[-1]}"
    return anchor_dir(video_dir, anchor_name) / started.strftime("%Y-%m-%d") / leaf


def analytics_dir(video_dir: Path, anchor_name: str) -> Path:
    return anchor_dir(video_dir, anchor_name) / "直播数据"


def target_key(anchor_name: str) -> str:
    digest = hashlib.sha1(anchor_name.encode("utf-8")).hexdigest()[:8]
    return f"{safe_path_name(anchor_name, 'target')}-{digest}"
