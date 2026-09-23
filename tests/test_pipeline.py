from __future__ import annotations

import logging
import threading
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import MediaFile, SessionStatus
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.recorder import RecordAttempt
from douyin_bili_recorder.uploader import UploadResult


class FakeRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, target, session_dir: Path, **_kwargs) -> RecordAttempt:
        self.calls += 1
        if self.calls > 1:
            return RecordAttempt(1, ["stream is offline"], [], False)
        media = session_dir / "part-000.ts"
        media.write_bytes(b"a" * 20)
        return RecordAttempt(0, [], [media], True)


class MultiSegmentRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, _target, session_dir: Path, **_kwargs) -> RecordAttempt:
        self.calls += 1
        if self.calls <= 2:
            media = session_dir / f"part-{self.calls - 1:03d}.ts"
            media.write_bytes(b"x" * 32)
            return RecordAttempt(0, [], [media], True)
        return RecordAttempt(1, ["stream is offline"], [], False)


class OverlapRecorder:
    def __init__(self, uploader: OverlapUploader) -> None:
        self.uploader = uploader
        self.calls = 0

    def record(self, _target, session_dir: Path, **_kwargs) -> RecordAttempt:
        self.calls += 1
        if self.calls == 1:
            media = session_dir / "part-000.ts"
            media.write_bytes(b"x" * 32)
            return RecordAttempt(0, [], [media], True)
        if self.calls == 2:
            self.uploader.release.set()
            media = session_dir / "part-001.ts"
            media.write_bytes(b"y" * 32)
            return RecordAttempt(0, [], [media], True)
        return RecordAttempt(1, ["stream is offline"], [], False)


class BoundaryRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, _target, session_dir: Path, **_kwargs) -> RecordAttempt:
        self.calls += 1
        if self.calls == 1:
            full = session_dir / "full-001.ts"
            tail = session_dir / "full-002.ts.part"
            full.write_bytes(b"x" * 64)
            tail.write_bytes(b"y" * 4)
            return RecordAttempt(0, [], [full, tail], True)
        if self.calls == 2:
            full = session_dir / "full-003.ts"
            full.write_bytes(b"z" * 64)
            return RecordAttempt(0, [], [full], True)
        return RecordAttempt(1, ["stream is offline"], [], False)


class FakeMedia:
    def process_file(self, source: Path, _session_dir: Path, **_kwargs) -> MediaFile:
        return MediaFile(
            path=source.name,
            size=source.stat().st_size,
            duration_seconds=10.0,
        )


class OverlapUploader:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.overlapped = False
        self.parts: list[int] = []

    def upload_session(self, *_args, **_kwargs) -> UploadResult:
        return UploadResult("BV0000000003", True, [])

    def upload_part(self, _target, _session, _media_path, *, part_index, title, bvid=None) -> UploadResult:
        self.parts.append(part_index)
        if part_index == 1:
            self.started.set()
            self.release.wait(timeout=2)
            self.overlapped = self.started.is_set() and self.release.is_set()
        return UploadResult(bvid or "BV0000000003", True, [])


class FakeUploader:
    def __init__(self) -> None:
        self.title = ""
        self.parts: list[tuple[int, str | None]] = []

    def upload_session(self, _target, _session, _session_dir, title=None) -> UploadResult:
        self.title = title or ""
        return UploadResult("BV0000000002", True, [])

    def upload_part(self, _target, _session, _media_path, *, part_index, title, bvid=None) -> UploadResult:
        self.title = title
        self.parts.append((part_index, bvid))
        return UploadResult(bvid or "BV0000000002", True, [])


class FakeStatus:
    live = True
    web_rid = "123"
    room_title = "测试直播间"


class FakeResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, _url):
        self.calls += 1
        return FakeStatus() if self.calls == 1 else type(
            "Offline", (), {"live": False, "web_rid": "123", "room_title": ""}
        )()


def test_recording_continues_while_previous_part_uploads(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"
reconnect_grace_minutes = 0

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    uploader = OverlapUploader()
    service.recorder = OverlapRecorder(uploader)  # type: ignore[assignment]
    service.media = FakeMedia()  # type: ignore[assignment]
    service.resolver = FakeResolver()  # type: ignore[assignment]
    service.uploader = uploader  # type: ignore[assignment]

    assert service.record_and_upload(config.targets[0]) is True
    assert uploader.parts == [1, 2]
    assert uploader.overlapped is True



def test_boundary_tail_partial_is_not_uploaded_as_short_part(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"
reconnect_grace_minutes = 0

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    service.recorder = BoundaryRecorder()  # type: ignore[assignment]
    service.media = FakeMedia()  # type: ignore[assignment]
    service.resolver = FakeResolver()  # type: ignore[assignment]
    service.uploader = FakeUploader()  # type: ignore[assignment]

    assert service.record_and_upload(config.targets[0]) is True
    record = service.status()[0]
    assert [part.index for part in record.parts] == [1, 2]
    assert not (config.sessions_dir / record.session_id / "full-002.ts.part").exists()


def test_pipeline_records_and_uploads_with_anchor_title(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"
reconnect_grace_minutes = 0

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
    service.resolver = FakeResolver()  # type: ignore[assignment]
    uploader = FakeUploader()
    service.uploader = uploader  # type: ignore[assignment]

    assert service.record_and_upload(config.targets[0]) is True
    records = service.status()
    assert len(records) == 1
    assert records[0].status == SessionStatus.UPLOADED
    assert records[0].bvid == "BV0000000002"
    assert records[0].title.startswith("imxiaoxin｜")


def test_pipeline_appends_later_segments_to_same_bvid(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"
reconnect_grace_minutes = 0

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
enabled = true
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    service.recorder = MultiSegmentRecorder()  # type: ignore[assignment]
    service.media = FakeMedia()  # type: ignore[assignment]
    service.resolver = FakeResolver()  # type: ignore[assignment]
    uploader = FakeUploader()
    service.uploader = uploader  # type: ignore[assignment]

    assert service.record_and_upload(config.targets[0]) is True
    record = service.status()[0]
    assert [part.index for part in record.parts] == [1, 2]
    assert all(part.status == "UPLOADED" for part in record.parts)
    assert uploader.parts == [(1, None), (2, "BV0000000002")]
