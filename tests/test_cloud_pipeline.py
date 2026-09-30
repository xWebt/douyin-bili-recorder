from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.cloud_uploader import CloudUploadResult
from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord
from douyin_bili_recorder.pipeline import RecorderService


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
delete_after_upload = true

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
cloud_backup = true
cloud_remote = "openlist:/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_cleanup_waits_for_cloud_backup_and_deletes_after_success(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        cloud_backup=True,
        cloud_remote="openlist:/DouyinBiliRecorder",
        parts=[SessionPart(index=1, status="UPLOADED", path=str(media), cloud_status="PENDING")],
    )

    service._cleanup_uploaded_artifacts(session)
    assert media.exists()

    session.parts[0].cloud_status = "UPLOADED"
    service._cleanup_uploaded_artifacts(session)
    assert not media.exists()


def test_cloud_backup_job_marks_uploaded_without_blocking_bilibili(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        cloud_backup=True,
        cloud_remote="openlist:/DouyinBiliRecorder",
        parts=[SessionPart(index=1, status="UPLOAD_FAILED", path=str(media))],
    )

    class CloudStub:
        def upload_part(self, _target, _session, _part):
            return CloudUploadResult(
                True,
                ["openlist:/DouyinBiliRecorder/anchor/2026-09-30/P01/part.mp4"],
                ["ok"],
            )

    service.cloud_uploader = CloudStub()  # type: ignore[assignment]
    ok = service._cloud_backup_job(config.targets[0], session, session.parts[0])

    assert ok is True
    assert session.parts[0].cloud_status == "UPLOADED"
    assert media.exists()
