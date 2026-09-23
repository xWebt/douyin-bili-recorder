from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import MediaFile, SessionStatus
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.recorder import RecordAttempt
from douyin_bili_recorder.uploader import UploadResult


class FakeRecorder:
    def record(self, target, session_dir: Path) -> RecordAttempt:
        media = session_dir / "part-000.ts"
        media.write_bytes(b"a" * 20)
        return RecordAttempt(0, [], [media])


class FakeMedia:
    def process(self, session_dir: Path) -> list[MediaFile]:
        media = session_dir / "part-000.mp4"
        media.write_bytes(b"b" * 20)
        return [MediaFile(path="part-000.mp4", size=20, duration_seconds=10.0)]


class FakeUploader:
    def __init__(self) -> None:
        self.title = ""

    def upload_session(self, _target, _session, _session_dir, title=None) -> UploadResult:
        self.title = title or ""
        return UploadResult("BV0000000002", True, [])


def test_pipeline_records_and_uploads_with_anchor_title(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "imxiaoxin"
url = "https://live.douyin.com/123"
title_template = "{name}｜{start_date} {start_time} 开播｜{room_title}"
tags = ["直播录像"]
enabled = true
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    service.recorder = FakeRecorder()  # type: ignore[assignment]
    service.media = FakeMedia()  # type: ignore[assignment]
    uploader = FakeUploader()
    service.uploader = uploader  # type: ignore[assignment]

    assert service.record_and_upload(config.targets[0]) is True
    records = service.status()
    assert len(records) == 1
    assert records[0].status == SessionStatus.UPLOADED
    assert records[0].bvid == "BV0000000002"
    assert records[0].title.startswith("imxiaoxin｜")
