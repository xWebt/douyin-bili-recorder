from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.danmaku import DanmakuRenderer, build_ass
from douyin_bili_recorder.process import ProcessResult


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args, **_kwargs) -> ProcessResult:
        command = [str(item) for item in args]
        self.commands.append(command)
        Path(command[-1]).write_bytes(b"burned")
        return ProcessResult(0, [])


def test_build_ass_uses_slow_staggered_right_to_left_motion(tmp_path: Path) -> None:
    xml = tmp_path / "danmaku.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<i>
  <d p="0.1,1,25,16777215,1,0,0,0">第一条弹幕</d>
  <d p="0.1,1,25,16777215,1,0,0,0">第二条弹幕</d>
</i>
""",
        encoding="utf-8",
    )
    ass = tmp_path / "danmaku.ass"

    count = build_ass(xml, ass, 1920, 1080)
    content = ass.read_text(encoding="utf-8")

    assert count == 2
    assert content.count(r"\move(") == 2
    assert r"\an7" in content
    assert "Hiragino Sans GB" in content
    assert "0:00:00.25" in content
    assert "0:00:00.90" in content


def test_renderer_burns_ass_then_removes_temporary_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[upload]
ffmpeg_bin = "ffmpeg"
ffprobe_bin = "ffprobe"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
record_danmaku = true
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    source = tmp_path / "source.flv"
    source.write_bytes(b"video")
    xml = tmp_path / "source.xml"
    xml.write_text(
        '<i><d p="0.1,1,25,16777215,1,0,0,0">hello</d></i>',
        encoding="utf-8",
    )
    output = tmp_path / "output.mp4"
    runner = FakeRunner()
    renderer = DanmakuRenderer(config, runner, logging.getLogger("test"))
    renderer.probe_size = lambda _path: (1280, 720)  # type: ignore[method-assign]

    count = renderer.render(source, xml, output, quality="origin", frame_rate="source")

    assert count == 1
    assert output.read_bytes() == b"burned"
    assert not output.with_suffix(".ass").exists()
    assert any("ass=" in item for item in runner.commands[0])
