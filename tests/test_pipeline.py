from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import MediaFile, SessionPart, SessionRecord, SessionStatus
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.recorder import RecordAttempt
from douyin_bili_recorder.state import SessionStore
from douyin_bili_recorder.uploader import UploadResult
from douyin_bili_recorder.webapp import _clear_target_cache


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
            duration_seconds=60.0,
        )

    def probe_duration(self, _path: Path) -> float:
        return 60.0


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

    def cancel(self, _key: str) -> None:
        return None

    def reset_cancel(self, _key: str) -> None:
        return None

    def upload_session(self, _target, _session, _session_dir, title=None) -> UploadResult:
        self.title = title or ""
        return UploadResult("BV0000000002", True, [])

    def upload_part(self, _target, _session, _media_path, *, part_index, title, bvid=None) -> UploadResult:
        self.title = title
        self.parts.append((part_index, bvid))
        return UploadResult(bvid or "BV0000000002", True, [])


class BlockingPartUploader:
    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def upload_part(self, _target, _session, _media_path, *, part_index, title, bvid=None) -> UploadResult:
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=2)
        return UploadResult(bvid or "BV0000000009", True, [])

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


def test_running_service_starts_workers_for_new_targets(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "first"
url = "https://live.douyin.com/1"
watch_mode = "all_day"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    started: list[str] = []
    lock = threading.Lock()

    def fake_loop(target) -> None:
        with lock:
            started.append(target.name)
        service.shutdown_event.wait(5)

    monkeypatch.setattr(service, "_target_loop", fake_loop)

    assert service._sync_target_workers() == {"first"}
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """

[[targets]]
name = "second"
url = "https://live.douyin.com/2"
watch_mode = "all_day"
""",
        encoding="utf-8",
    )

    assert service._sync_target_workers() == {"first", "second"}
    assert set(started) == {"first", "second"}
    service.shutdown_event.set()
    for worker in service._target_workers.values():
        worker.join(timeout=1)


def test_live_target_continues_after_schedule_end(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"
timezone = "Asia/Shanghai"

[storage]
video_dir = "videos"
reconnect_grace_minutes = 15

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
watch_mode = "scheduled"

[[targets.schedule]]
days = [1, 2, 3, 4, 5, 6, 7]
start = "20:00"
end = "21:00"
enabled = true
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    target = config.targets[0]
    moment = datetime(2026, 9, 29, 21, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert service._schedule_allows_polling(target, moment) is False
    service._last_live_epoch[target.name] = int((moment - timedelta(minutes=5)).timestamp())
    assert service._schedule_allows_polling(target, moment) is True
    service._last_live_epoch[target.name] = int((moment - timedelta(minutes=20)).timestamp())
    assert service._schedule_allows_polling(target, moment) is False


def test_offline_target_skips_capacity_wait(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "offline"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    monkeypatch.setattr(service, "_is_live", lambda _target: False)
    monkeypatch.setattr(
        service,
        "_wait_for_capacity",
        lambda _target: (_ for _ in ()).throw(AssertionError("offline target must not wait for cache space")),
    )

    assert service.record_and_upload(config.targets[0]) is False


def test_part_upload_lock_serializes_threads(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    acquired = threading.Event()
    release = threading.Event()

    def contender() -> None:
        with service._part_upload_lock("session", 1):
            acquired.set()
        release.set()

    with service._part_upload_lock("session", 1):
        thread = threading.Thread(target=contender)
        thread.start()
        assert not acquired.wait(0.1)
    assert acquired.wait(1)
    thread.join(timeout=1)
    assert release.is_set()


def test_removed_target_interrupts_capacity_wait(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    config.max_cache_gb = 1
    service = RecorderService(config, logging.getLogger("test"))
    target = config.targets[0]
    entered_wait = threading.Event()
    release_wait = threading.Event()

    class WaitingEvent:
        @staticmethod
        def is_set() -> bool:
            return False

        @staticmethod
        def wait(_seconds: float) -> bool:
            entered_wait.set()
            release_wait.wait(timeout=1)
            return False

    monkeypatch.setattr(service, "shutdown_event", WaitingEvent())
    monkeypatch.setattr(service.storage, "enforce_limit", lambda _limit: None)
    monkeypatch.setattr(service, "_managed_usage_bytes", lambda: 2 * 1024**3)
    service._pending_uploads["session"] = [Future()]
    results: list[bool] = []
    worker = threading.Thread(target=lambda: results.append(service._wait_for_capacity(target)))
    worker.start()
    assert entered_wait.wait(1)
    service._removed_targets.add(target.name)
    release_wait.set()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert results == [False]


def test_second_upload_worker_skips_completed_part(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    uploader = BlockingPartUploader()
    service.uploader = uploader  # type: ignore[assignment]
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        parts=[SessionPart(index=1, status="PENDING", title="anchor P01", path="/tmp/part.mp4")],
    )
    service.store.save(session)
    results: list[UploadResult] = []

    def upload(candidate: SessionRecord) -> None:
        part = candidate.parts[0]
        results.append(
            service._upload_part_with_retries(
                config.targets[0],
                candidate,
                Path(part.path),
                part,
            )
        )

    first = threading.Thread(target=upload, args=(session,))
    first.start()
    assert uploader.started.wait(1)
    second_session = service.store.load(session.session_id)
    second = threading.Thread(target=upload, args=(second_session,))
    second.start()
    uploader.release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive()
    assert not second.is_alive()
    assert uploader.calls == 1
    assert len(results) == 2
    assert all(result.verified for result in results)
    assert service.store.load(session.session_id).parts[0].status == "UPLOADED"


def test_recover_pending_uploads_sessions_in_parallel(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    uploader = BlockingPartUploader()
    service.uploader = uploader  # type: ignore[assignment]
    for index in range(2):
        media = tmp_path / f"part-{index}.mp4"
        media.write_bytes(b"video")
        service.store.save(
            SessionRecord(
                session_id=f"session-{index}",
                target_name="anchor",
                target_url="https://live.douyin.com/1",
                status=SessionStatus.RECORDED,
                parts=[SessionPart(index=1, status="PENDING", title=f"P{index}", path=str(media))],
            )
        )

    service.recover_pending()
    assert uploader.started.wait(1)
    deadline = time.monotonic() + 1
    while uploader.calls < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert uploader.calls == 2
    uploader.release.set()


def test_manual_request_bypasses_schedule_for_scheduled_target(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
watch_mode = "scheduled"

[[targets.schedule]]
days = [1, 2, 3, 4, 5, 6, 7]
start = "20:00"
end = "21:00"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    target = config.targets[0]
    checked: list[str] = []
    monkeypatch.setattr(service, "_reload_runtime_settings", lambda _target: None)
    monkeypatch.setattr(service, "_consume_manual_request", lambda _target: True)
    monkeypatch.setattr(service, "_schedule_allows_polling", lambda _target, _now: False)
    monkeypatch.setattr(service, "_set_target_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "record_and_upload", lambda candidate: checked.append(candidate.name) or False)
    monkeypatch.setattr(service, "_wait_for_stop", lambda _seconds: True)

    service._target_loop(target)

    assert checked == ["anchor"]


def test_retry_title_replaces_previous_retry_suffix_and_stays_within_limit() -> None:
    first = RecorderService._retry_title("主播｜2026-09-30 02:22 开播｜P01", 1)
    second = RecorderService._retry_title(first, 2)
    assert first.endswith("｜重试01")
    assert second.endswith("｜重试02")
    assert first not in second
    long_title = RecorderService._retry_title("主" * 100, 12)
    assert long_title.endswith("｜重试12")
    assert len(long_title) <= 80


def test_upload_pause_retry_and_stop_are_isolated(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    service.store.save(
        SessionRecord(
            session_id="session",
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.RECORDED,
            parts=[SessionPart(index=1, status="PENDING", title="anchor P01", path=str(media))],
        )
    )

    service._handle_upload_control("pause", "session", 1)
    assert service.store.load("session").parts[0].status == "PAUSED"
    assert service._upload_is_paused("session", 1)
    assert service._upload_is_cancelled("session", 1)

    uploader = FakeUploader()
    service.uploader = uploader  # type: ignore[assignment]
    service._handle_upload_control("retry", "session", 1)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if service.store.load("session").parts[0].status == "UPLOADED":
            break
        time.sleep(0.01)
    assert service.store.load("session").parts[0].status == "UPLOADED"
    assert uploader.parts == [(1, None)]
    assert not service._upload_is_paused("session", 1)
    assert not service._upload_is_cancelled("session", 1)

    service.store.save(
        SessionRecord(
            session_id="stopped",
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.RECORDED,
            parts=[SessionPart(index=1, status="PENDING", title="P1", path=str(media))],
        )
    )
    service._handle_upload_control("stop", "stopped", 1)
    assert service.store.load("stopped").parts[0].status == "CANCELED"
    assert service._upload_is_cancelled("stopped", 1)

    service.store.save(
        SessionRecord(
            session_id="paused",
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.RECORDED,
            parts=[SessionPart(index=1, status="PAUSED", title="P1", path=str(media))],
        )
    )
    service._upload_with_retries(service.store.load("paused"))
    assert service.store.load("paused").parts[0].status == "PAUSED"


def test_clear_target_cache_keeps_active_and_pending_files(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    config.video_dir.mkdir(parents=True, exist_ok=True)
    uploaded = config.video_dir / "uploaded.mp4"
    active = config.video_dir / "active.mp4"
    pending = config.video_dir / "pending.mp4"
    uploaded.write_bytes(b"a" * 10)
    active.write_bytes(b"b" * 20)
    pending.write_bytes(b"c" * 30)
    store = SessionStore(config.sessions_dir)
    store.save(
        SessionRecord(
            session_id="uploaded",
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.UPLOADED,
            bvid="BV0000000001",
            parts=[SessionPart(index=1, status="UPLOADED", path=str(uploaded), bvid="BV0000000001")],
        )
    )
    store.save(
        SessionRecord(
            session_id="active",
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.RECORDING,
            parts=[SessionPart(index=1, status="UPLOADING", path=str(active))],
        )
    )
    store.save(
        SessionRecord(
            session_id="pending",
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.RECORDED,
            parts=[SessionPart(index=1, status="PENDING", path=str(pending))],
        )
    )

    result = _clear_target_cache(config, "anchor")

    assert result["freed_bytes"] == 10
    assert result["skipped_active_sessions"] == 1
    assert not uploaded.exists()
    assert active.exists()
    assert pending.exists()


def test_run_forever_exits_after_interrupt_without_active_recording(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    service.interrupt_event.set()
    worker = threading.Thread(target=service.run_forever)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert service.shutdown_event.is_set()


def test_record_and_upload_ensures_cloud_anchor_before_recording(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
cloud_remote = "quark:/quark/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    calls = []

    class FakeCloudUploader:
        @staticmethod
        def ensure_anchor_dir(name, remote):
            calls.append((name, remote))
            return remote

    service.cloud_uploader = FakeCloudUploader()  # type: ignore[assignment]
    service._is_live = lambda _target: True  # type: ignore[method-assign]
    service._wait_for_capacity = lambda _target: False  # type: ignore[method-assign]

    assert service.record_and_upload(config.targets[0]) is False
    assert calls == [("anchor", "quark:/quark/DouyinBiliRecorder")]


def test_canceled_parts_are_not_queued_for_cloud_backup(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
cloud_backup = true
cloud_remote = "quark:/quark/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "canceled.flv"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="canceled",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status="CANCELED",
        parts=[SessionPart(index=1, status="CANCELED", path=str(media))],
    )

    service._queue_pending_cloud_parts(session, config.targets[0])

    assert service._pending_cloud_uploads == {}
