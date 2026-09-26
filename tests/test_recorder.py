from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.recorder import discover_media
from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.recorder import BiliupRecorder


def test_discover_media_sorts_and_filters(tmp_path: Path) -> None:
    first = tmp_path / "part-000.ts"
    second = tmp_path / "part-001.mp4"
    ignored = tmp_path / "note.txt"
    first.write_bytes(b"a" * 1024)
    second.write_bytes(b"b" * 2048)
    ignored.write_bytes(b"c" * 4096)

    files = discover_media(tmp_path, min_file_size_mb=0)
    assert [path.name for path in files] == ["part-000.ts", "part-001.mp4"]

    files = discover_media(tmp_path, min_file_size_mb=1)
    assert files == []


def test_discover_media_keeps_active_partial_below_normal_threshold(tmp_path: Path) -> None:
    initialized = tmp_path / "live.flv"
    initialized.write_bytes(b"a" * 1024)
    active = tmp_path / "live.flv.part"
    active.write_bytes(b"b" * 4096)

    files = discover_media(tmp_path, min_file_size_mb=10, allow_partials=True)

    assert files == [active]


class RecordingRunner:
    def __init__(self) -> None:
        self.command: list[str] = []
        self.cwd: Path | None = None

    def start(self, args, *, cwd=None):
        self.command = [str(item) for item in args]
        self.cwd = cwd
        return object()


def test_danmaku_target_starts_server_with_douyin_danmaku_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[recording]
segment_time = "1h"

[storage]
video_dir = "videos"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
record_danmaku = true
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    runner = RecordingRunner()
    recorder = BiliupRecorder(config, runner, __import__("logging").getLogger("test"))
    session_dir = config.sessions_dir / "session"
    session_dir.mkdir(parents=True)
    recorder.start(config.targets[0], session_dir)

    assert runner.command[1] == "server"
    assert "--config" in runner.command
    assert runner.cwd == session_dir / ".danmaku-runtime"
    generated = Path(runner.command[runner.command.index("--config") + 1])
    payload = __import__("tomllib").loads(generated.read_text(encoding="utf-8"))
    assert payload["douyin_danmaku"] is True
    assert payload["uploader"] == "Noop"
    assert payload["filename_prefix"] == "%Y-%m-%dT%H_%M_%S{title}"
