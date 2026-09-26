from __future__ import annotations

import logging
import threading
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import MediaFile, SessionRecord, SessionStatus
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.recorder import RecordAttempt
from douyin_bili_recorder.uploader import UploadResult


class FakeRunningProcess:
    def __init__(self, lines: list[str], returncode: int) -> None:
        self._lines = lines
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def output(self) -> list[str]:
        return self._lines


class ContinuousProcess:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.stage = 0
        self.returncode = 0

    def poll(self) -> int | None:
        if self.stage == 0:
            self.stage = 1
            (self.session_dir / "full-002.ts").write_bytes(b"b" * 64)
            return None
        return 0

    def output(self) -> list[str]:
        return []


class FakeRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def start(self, target, session_dir: Path):
        attempt = self.record(target, session_dir)
        return FakeRunningProcess(attempt.lines, attempt.returncode)

    def record(self, target, session_dir: Path, **_kwargs) -> RecordAttempt:
        self.calls += 1
        if self.calls > 1:
            return RecordAttempt(1, ["stream is offline"], [], False)
        media = session_dir / "part-000.ts"
        media.write_bytes(b"a" * 20)
        return RecordAttempt(0, [], [media], True)


class ContinuousRecorder:
    def __init__(self) -> None:
        self.starts = 0

    def start(self, _target, session_dir: Path):
        self.starts += 1
        if self.starts == 1:
            (session_dir / "full-001.ts").write_bytes(b"a" * 64)
            return ContinuousProcess(session_dir)
        return FakeRunningProcess(["stream is offline"], 1)


class LingeringOfflineProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def output(self) -> list[str]:
        return ["stream is offline"]

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1


class OfflineRecorder:
    def __init__(self) -> None:
        self.last_process: LingeringOfflineProcess | None = None

    def start(self, _target, _session_dir: Path):
        self.last_process = LingeringOfflineProcess()
        return self.last_process


class MultiSegmentRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def start(self, target, session_dir: Path):
        attempt = self.record(target, session_dir)
        return FakeRunningProcess(attempt.lines, attempt.returncode)

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

    def start(self, target, session_dir: Path):
        attempt = self.record(target, session_dir)
        return FakeRunningProcess(attempt.lines, attempt.returncode)

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

    def start(self, target, session_dir: Path):
        attempt = self.record(target, session_dir)
        return FakeRunningProcess(attempt.lines, attempt.returncode)

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

    def probe_duration(self, _path: Path) -> float:
        return 10.0


class FakeDanmakuRenderer:
    def render(self, _source: Path, _xml: Path, output: Path, **_kwargs) -> int:
        output.write_bytes(b"burned-danmaku")
        return 2


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
        return FakeStatus() if self.calls <= 2 else type(
            "Offline", (), {"live": False, "web_rid": "123", "room_title": ""}
        )()


class OfflineResolvedStatus:
    live = False
    web_rid = "123"
    room_title = ""


def test_live_check_probes_when_resolver_reports_offline_room(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
record_danmaku = true
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    service.resolver = type("Resolver", (), {"resolve": lambda _self, _url: OfflineResolvedStatus()})()  # type: ignore[assignment]
    monkeypatch.setattr(service, "_probe_live_with_recorder", lambda _target: True)

    assert service._is_live(config.targets[0]) is True


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



def test_final_partial_content_is_preserved(tmp_path: Path) -> None:
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
    assert [part.index for part in record.parts] == [1, 2, 3]
    assert record.parts[1].path.endswith(".ts")
    assert not (config.sessions_dir / record.session_id / "full-002.ts.part").exists()


def test_one_process_can_finalize_multiple_full_parts(tmp_path: Path) -> None:
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
    recorder = ContinuousRecorder()
    service.recorder = recorder  # type: ignore[assignment]
    service.media = FakeMedia()  # type: ignore[assignment]
    service.resolver = FakeResolver()  # type: ignore[assignment]
    service.uploader = FakeUploader()  # type: ignore[assignment]

    assert service.record_and_upload(config.targets[0]) is True
    record = service.status()[0]
    assert [part.index for part in record.parts] == [1, 2]
    assert recorder.starts == 2


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


def test_offline_probe_without_media_skips_reconnect_grace(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"
reconnect_grace_minutes = 15

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
    recorder = OfflineRecorder()
    service.recorder = recorder  # type: ignore[assignment]
    service.resolver = FakeResolver()  # type: ignore[assignment]

    def fail_if_reconnect_wait(*_args, **_kwargs):
        raise AssertionError("offline probes without media must not enter reconnect grace")

    monkeypatch.setattr(service, "_wait_for_reconnect", fail_if_reconnect_wait)
    assert service.record_and_upload(config.targets[0]) is False
    assert recorder.last_process is not None
    assert recorder.last_process.terminated is True


def test_reconnect_grace_is_preserved_after_real_recording(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"
reconnect_grace_minutes = 15

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
    service.recorder = FakeRecorder()  # type: ignore[assignment]
    service.media = FakeMedia()  # type: ignore[assignment]
    service.resolver = FakeResolver()  # type: ignore[assignment]
    service.uploader = FakeUploader()  # type: ignore[assignment]
    reconnect_waits: list[tuple[object, object]] = []

    def record_reconnect_wait(target, session):
        reconnect_waits.append((target, session))
        return False

    monkeypatch.setattr(service, "_wait_for_reconnect", record_reconnect_wait)
    assert service.record_and_upload(config.targets[0]) is True
    assert reconnect_waits
    assert reconnect_waits[0][1].detected_start_epoch is not None


def test_prepare_part_moves_matching_danmaku_xml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
record_danmaku = true
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    service.media = FakeMedia()  # type: ignore[assignment]
    session_dir = config.sessions_dir / "session"
    session_dir.mkdir(parents=True)
    source = session_dir / "capture.flv"
    source.write_bytes(b"video")
    danmaku = session_dir / "capture.xml"
    danmaku.write_text("<i><d p=\"1,1,25,16777215\">hello</d></i>", encoding="utf-8")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/123",
        detected_start_epoch=1,
        detected_start_iso="2026-09-26T00:00:00+08:00",
    )

    part = service._prepare_part(config.targets[0], session, session_dir, source, 1)

    assert part is not None
    assert part.danmaku_path.endswith(".xml")
    assert Path(part.danmaku_path).exists()
    assert not danmaku.exists()


def test_prepare_part_burns_danmaku_into_uploaded_mp4(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
min_file_size_mb = 0
keep_original_files = true

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
record_danmaku = true
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    service.media = FakeMedia()  # type: ignore[assignment]
    service.danmaku = FakeDanmakuRenderer()  # type: ignore[assignment]
    session_dir = config.sessions_dir / "session"
    session_dir.mkdir(parents=True)
    source = session_dir / "capture.flv"
    source.write_bytes(b"video")
    xml = session_dir / "capture.xml"
    xml.write_text("<i><d p=\"0.1,1,25,16777215,1,0,0,0\">hello</d></i>", encoding="utf-8")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/123",
        detected_start_epoch=1,
        detected_start_iso="2026-09-26T00:00:00+08:00",
    )

    part = service._prepare_part(config.targets[0], session, session_dir, source, 1)

    assert part is not None
    assert part.path.endswith(".mp4")
    assert Path(part.path).read_bytes() == b"burned-danmaku"
    assert Path(part.source_path).exists()
    assert Path(part.danmaku_path).exists()
