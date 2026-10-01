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
                ["openlist:/DouyinBiliRecorder/anchor/2026-09-30/part.mp4"],
                ["ok"],
            )

    service.cloud_uploader = CloudStub()  # type: ignore[assignment]
    ok = service._cloud_backup_job(config.targets[0], session, session.parts[0])

    assert ok is True
    assert session.parts[0].cloud_status == "UPLOADED"
    assert media.exists()


def test_retry_cloud_only_does_not_call_bilibili_uploader(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.min_file_size_mb = 0
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status="RECORDED",
        cloud_backup=True,
        cloud_remote="openlist:/DouyinBiliRecorder",
        parts=[
            SessionPart(
                index=1,
                status="UPLOAD_FAILED",
                cloud_status="FAILED",
                path=str(media),
            )
        ],
    )
    service.store.save(session)

    class CloudStub:
        def __init__(self) -> None:
            self.calls = 0

        def upload_part(self, _target, _session, _part):
            self.calls += 1
            return CloudUploadResult(True, ["openlist:/anchor/date/part.mp4"], ["ok"])

    class BilibiliStub:
        def upload_part(self, *_args, **_kwargs):
            raise AssertionError("Bilibili uploader must not run")

    cloud = CloudStub()
    service.cloud_uploader = cloud  # type: ignore[assignment]
    service.uploader = BilibiliStub()  # type: ignore[assignment]

    result = service.retry_cloud_only("anchor")

    assert result == {"processed": 1, "uploaded": 1, "failed": 0, "skipped": 0}
    assert cloud.calls == 1
