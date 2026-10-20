from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import pytest

from douyin_bili_recorder.cloud import create_driver
from douyin_bili_recorder.cloud.driver import CloudDriverError, DriverContext
from douyin_bili_recorder.quark_official import QuarkOfficialClientError
from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.process import ProcessResult


class FakeRunner:
    def __init__(self, remote_size: int) -> None:
        self.remote_size = remote_size
        self.commands: list[list[str]] = []

    def run(self, args, **_kwargs) -> ProcessResult:
        command = [str(item) for item in args]
        self.commands.append(command)
        if command[1:2] == ["size"]:
            return ProcessResult(0, [json.dumps({"bytes": self.remote_size})])
        return ProcessResult(0, ["ok"])


def _config(tmp_path: Path, sync_dir: Path | None):
    config_path = tmp_path / "config.toml"
    sync_value = str(sync_dir) if sync_dir is not None else ""
    config_path.write_text(
        f"""
[app]
data_dir = "data"

[cloud]
rclone_bin = "rclone"
quark_sync_dir = "{sync_value}"
quark_sync_remote_root = "quark:/quark/DouyinBiliRecorder"
quark_sync_timeout_seconds = 60

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
cloud_backup = true
cloud_provider = "quark"
cloud_remote = "quark:/quark/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    return load_config(config_path)


def test_sync_folder_driver_copies_and_verifies(tmp_path: Path, monkeypatch) -> None:
    sync_dir = tmp_path / "QuarkSync"
    sync_dir.mkdir()
    monkeypatch.setattr(
        "douyin_bili_recorder.cloud.quark_sync.ensure_official_backup_directory",
        lambda _path: {"task": {"path": str(sync_dir)}},
    )
    config = _config(tmp_path, sync_dir)
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    runner = FakeRunner(len(b"video"))
    context = DriverContext(config=config, runner=runner, logger=logging.getLogger("test"))

    driver = create_driver("quark", "quark:/quark/DouyinBiliRecorder", context)
    assert driver.name == "quark-sync-vip"

    remote = "quark:/quark/DouyinBiliRecorder/anchor/2026-10-20/part.mp4"
    driver.ensure_dir(remote.rsplit("/", 1)[0], threading.Event())
    outcome = driver.upload(media, remote, threading.Event())

    assert outcome.remote_paths == [remote]
    copied = sync_dir / "anchor/2026-10-20/part.mp4"
    assert copied.read_bytes() == b"video"
    assert runner.commands[-1][1:2] == ["size"]


def test_sync_folder_driver_rejects_missing_official_backup_task(
    tmp_path: Path, monkeypatch
) -> None:
    sync_dir = tmp_path / "QuarkSync"
    sync_dir.mkdir()
    config = _config(tmp_path, sync_dir)
    context = DriverContext(
        config=config,
        runner=FakeRunner(1),
        logger=logging.getLogger("test"),
    )

    def missing_task(_path):
        raise QuarkOfficialClientError("没有电脑备份任务")

    monkeypatch.setattr(
        "douyin_bili_recorder.cloud.quark_sync.ensure_official_backup_directory",
        missing_task,
    )

    with pytest.raises(CloudDriverError, match="电脑备份"):
        create_driver("quark", "quark:/quark/DouyinBiliRecorder", context)


def test_sync_folder_driver_is_disabled_when_dir_empty(tmp_path: Path) -> None:
    config = _config(tmp_path, None)
    context = DriverContext(
        config=config,
        runner=FakeRunner(1),
        logger=logging.getLogger("test"),
    )

    driver = create_driver("quark", "quark:/quark/DouyinBiliRecorder", context)

    assert driver.name != "quark-sync-vip"
