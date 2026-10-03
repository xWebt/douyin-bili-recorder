from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from douyin_bili_recorder.cloud import create_driver, detect_provider
from douyin_bili_recorder.cloud.driver import DriverContext
from douyin_bili_recorder.cloud.openlist import OpenListDriver
from douyin_bili_recorder.cloud.quark import QuarkCliDriver
from douyin_bili_recorder.cloud.rclone import RcloneDriver
from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.process import ProcessResult


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args, **_kwargs) -> ProcessResult:
        self.commands.append([str(item) for item in args])
        return ProcessResult(0, ["ok"])


def _config(tmp_path: Path, extra_cloud: str = ""):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[app]
data_dir = "data"

[cloud]
rclone_bin = "rclone"
{extra_cloud}

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
cloud_backup = true
cloud_provider = "quark"
cloud_remote = "quark:/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    return load_config(config_path)


def _fake_cli(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_detect_provider_from_remote_name() -> None:
    assert detect_provider("quark:/root") == "quark"
    assert detect_provider("uc-drive:/root") == "quark"
    assert detect_provider("baidu:/root") == "baidu"
    assert detect_provider("mypan:/root") == "baidu"
    assert detect_provider("openlist:/root") == "custom"


def test_quark_without_cli_falls_back_to_openlist(tmp_path: Path) -> None:
    config = _config(tmp_path, 'quark_cli = "definitely-not-installed-quark"')
    context = DriverContext(config=config, runner=FakeRunner(), logger=logging.getLogger("test"))

    driver = create_driver("quark", "quark:/DouyinBiliRecorder", context)

    assert isinstance(driver, OpenListDriver)


def test_quark_cli_driver_uses_chunked_flags(tmp_path: Path) -> None:
    cli = _fake_cli(tmp_path, "quarkpan")
    config = _config(
        tmp_path,
        f'quark_cli = "{cli}"\nchunk_size_mb = 8\nmax_concurrency = 4\n'
        f'quark_cookie_file = "{tmp_path / "quark.txt"}"',
    )
    runner = FakeRunner()
    context = DriverContext(config=config, runner=runner, logger=logging.getLogger("test"))
    driver = create_driver("quark", "quark:/DouyinBiliRecorder", context)
    assert isinstance(driver, QuarkCliDriver)

    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    outcome = driver.upload(media, "quark:/DouyinBiliRecorder/anchor/part.mp4", None)  # type: ignore[arg-type]

    assert outcome.remote_paths == ["quark:/DouyinBiliRecorder/anchor/part.mp4"]
    command = runner.commands[0]
    assert command[0] == str(cli)
    assert "--chunk-size" in command
    assert "8M" in command
    assert "--concurrency" in command
    assert "4" in command


def test_rclone_driver_reports_multithread_and_limit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = FakeRunner()
    context = DriverContext(config=config, runner=runner, logger=logging.getLogger("test"))
    driver = RcloneDriver("openlist:/DouyinBiliRecorder", context)
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")

    driver.upload(media, "openlist:/DouyinBiliRecorder/a.mp4", None)  # type: ignore[arg-type]

    command = runner.commands[0]
    assert "--multi-thread-streams" in command
    assert driver.capabilities.chunked is True


def test_driver_context_uses_configured_binaries(tmp_path: Path) -> None:
    config = _config(tmp_path)
    context = DriverContext(config=config, runner=FakeRunner(), logger=logging.getLogger("test"))
    driver = create_driver("custom", "openlist:/root", context)

    assert isinstance(driver, OpenListDriver)
    assert os.fspath(config.cloud_rclone_bin) == "rclone"
