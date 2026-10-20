from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord, SessionStatus
from douyin_bili_recorder.pipeline import RecorderService


def _config(tmp_path: Path, *, policy: str = "wait", retention: int = 0):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[app]
data_dir = "data"

[storage]
video_dir = "videos"
max_cache_gb = 1
cache_full_policy = "{policy}"
failed_part_retention_days = {retention}
reconnect_grace_minutes = 15

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    return load_config(config_path)


def _failed_session(tmp_path: Path, *, age_days: float, cloud: bool = False) -> tuple[RecorderService, SessionRecord, Path]:
    config = _config(tmp_path, retention=1)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "failed.mp4"
    media.write_bytes(b"x" * 1024)
    old = time.time() - age_days * 86400
    os.utime(media, (old, old))
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status=SessionStatus.UPLOAD_FAILED,
        cloud_backup=cloud,
        parts=[
            SessionPart(
                index=1,
                status="UPLOAD_FAILED",
                path=str(media),
                cloud_status="FAILED" if cloud else "",
            )
        ],
    )
    service.store.save(session)
    return service, session, media


def test_expired_failed_part_is_removed_and_marked_unavailable(tmp_path: Path) -> None:
    service, _session, media = _failed_session(tmp_path, age_days=2, cloud=True)

    result = service.cleanup_expired_failed_parts()

    assert result["removed"] == 1
    assert not media.exists()
    loaded = service.store.load("session")
    assert loaded.parts[0].path == ""
    assert loaded.parts[0].cloud_status == "UNAVAILABLE"
    assert "保留策略" in loaded.parts[0].error


def test_recent_failed_part_is_kept(tmp_path: Path) -> None:
    service, _session, media = _failed_session(tmp_path, age_days=0)

    result = service.cleanup_expired_failed_parts()

    assert result["removed"] == 0
    assert media.exists()


def test_allow_policy_permits_recording_when_disk_has_space(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, policy="allow")
    service = RecorderService(config, logging.getLogger("test"))
    monkeypatch.setattr(service, "_managed_usage_bytes", lambda: 0)
    monkeypatch.setattr(
        "douyin_bili_recorder.pipeline.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=200 * 1024**3),
    )

    assert service._wait_for_capacity(config.targets[0]) is True


def test_wait_policy_blocks_and_keeps_error_status(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, policy="wait")
    service = RecorderService(config, logging.getLogger("test"))
    monkeypatch.setattr(service, "_managed_usage_bytes", lambda: 0)
    monkeypatch.setattr(
        "douyin_bili_recorder.pipeline.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=200 * 1024**3),
    )

    assert service._wait_for_capacity(config.targets[0]) is False
    status = service.target_status.load_all().get("anchor", {})
    assert status.get("state") == "error"
    assert "缓存空间不足" in str(status.get("message"))
