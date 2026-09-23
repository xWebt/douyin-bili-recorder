from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import MediaFile, SessionRecord, SessionStatus
from douyin_bili_recorder.process import ProcessResult
from douyin_bili_recorder.uploader import BiliupUploader


class FakeRunner:
    def __init__(self, title: str) -> None:
        self.title = title
        self.commands: list[list[str]] = []
        self.upload_seen = False

    def run(self, args, **_kwargs) -> ProcessResult:
        command = [str(item) for item in args]
        self.commands.append(command)
        if "upload" in command:
            self.upload_seen = True
            return ProcessResult(0, ["uploaded"])
        if "list" in command and self.upload_seen:
            return ProcessResult(0, [f"BV0000000001\t{self.title}\t审核中"])
        if "list" in command:
            return ProcessResult(0, [])
        return ProcessResult(0, [])


def test_upload_session_puts_anchor_name_first(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[upload]
cookie_file = "cookies.json"
line = "bda2"

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
    session_dir = config.sessions_dir / "session"
    session_dir.mkdir(parents=True)
    media = session_dir / "part-000.mp4"
    media.write_bytes(b"video")

    session = SessionRecord(
        session_id="session",
        target_name="imxiaoxin",
        target_url="https://live.douyin.com/123",
        status=SessionStatus.RECORDED,
        detected_start_epoch=1790165681,
        detected_start_iso="2026-09-23T20:14:41+08:00",
        files=[MediaFile(path="part-000.mp4", size=5)],
    )
    expected_title = "imxiaoxin｜2026-09-23 20:14 开播"
    runner = FakeRunner(expected_title)
    uploader = BiliupUploader(config, runner, logging.getLogger("test"))

    result = uploader.upload_session(config.targets[0], session, session_dir)

    assert result.verified is True
    assert result.bvid == "BV0000000001"
    upload_command = next(command for command in runner.commands if "upload" in command)
    assert expected_title in upload_command
    assert "--is-only-self" in upload_command
