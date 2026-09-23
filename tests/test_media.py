from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.media import MediaProcessor
from douyin_bili_recorder.process import ProcessResult


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args, **_kwargs) -> ProcessResult:
        command = [str(item) for item in args]
        self.commands.append(command)
        Path(command[-1]).write_bytes(b"converted")
        return ProcessResult(0, [])


def config_for(tmp_path: Path, quality: str = "origin", frame_rate: str = "source"):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[app]
data_dir = "data"

[recording]
quality = "{quality}"
frame_rate = "{frame_rate}"

[storage]
video_dir = "videos"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_origin_source_uses_flv_without_creating_mp4(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    source = config.sessions_dir / "session" / "part.flv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    runner = FakeRunner()
    processor = MediaProcessor(config, runner, logging.getLogger("test"))

    media = processor.process_file(source, source.parent, part_index=1)

    assert media is not None
    assert media.path == "part.flv"
    assert media.source is None
    assert runner.commands == []
    assert source.exists()


def test_requested_quality_transcodes_to_mp4(tmp_path: Path) -> None:
    config = config_for(tmp_path, quality="720p", frame_rate="30")
    source = config.sessions_dir / "session" / "part.flv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    runner = FakeRunner()
    processor = MediaProcessor(config, runner, logging.getLogger("test"))

    media = processor.process_file(source, source.parent, part_index=1)

    assert media is not None
    assert media.path == "part-001.mp4"
    assert runner.commands
    command = runner.commands[0]
    assert "-vf" in command
    assert "scale=-2:720" in command
    assert "-r" in command
    assert "30" in command
