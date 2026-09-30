from __future__ import annotations

import logging
import pytest
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import MediaFile, SessionPart, SessionRecord, SessionStatus
from douyin_bili_recorder.process import ProcessResult
from douyin_bili_recorder.uploader import BiliupUploader, UploadRateLimited


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
public = true
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
    assert "--is-only-self" not in upload_command


def test_upload_part_raises_rate_limit_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
enabled = true
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    config = load_config(config_path)

    class RateLimitedRunner:
        def run(self, args, **_kwargs) -> ProcessResult:
            command = [str(item) for item in args]
            if "list" in command:
                return ProcessResult(0, [])
            return ProcessResult(1, ["ResponseData { code: 21566, message: 投稿过于频繁 }"])

    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/123",
    )
    uploader = BiliupUploader(config, RateLimitedRunner(), logging.getLogger("test"))

    with pytest.raises(UploadRateLimited):
        uploader.upload_part(
            config.targets[0],
            session,
            media,
            part_index=1,
            title="anchor P01",
        )


def test_upload_rate_limit_detection_includes_bilibili_601() -> None:
    assert BiliupUploader._is_rate_limited([
        "ResponseData { code: 601, message: 您上传视频过快，请您稍作休息后再继续 }"
    ])
    assert BiliupUploader._is_rate_limited([
        "Failed to pre_upload from {\"OK\":0,\"info\":\"request limited\"}"
    ])


def test_upload_part_checks_existing_title_before_append(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
enabled = true
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    config = load_config(config_path)
    title = "anchor P02"

    class ExistingRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(self, args, **_kwargs) -> ProcessResult:
            command = [str(item) for item in args]
            self.commands.append(command)
            if "list" in command:
                return ProcessResult(0, [f"BV0000000002\t{title}\t审核中"])
            return ProcessResult(0, [])

    runner = ExistingRunner()
    uploader = BiliupUploader(config, runner, logging.getLogger("test"))
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/123",
        parts=[SessionPart(index=2, title=title, path="part.mp4")],
    )

    result = uploader.upload_part(
        config.targets[0],
        session,
        tmp_path / "part.mp4",
        part_index=2,
        title=title,
        bvid="BV0000000002",
    )

    assert result.verified is True
    assert result.bvid == "BV0000000002"
    assert all("append" not in command for command in runner.commands)
