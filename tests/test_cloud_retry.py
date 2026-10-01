from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.cloud_retry import CloudRetryManager
from douyin_bili_recorder.config import load_config


def test_cloud_retry_uses_runtime_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[[targets]]
name = "example"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    runtime_path = config.data_dir / "ui" / "runtime-config.toml"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        """
[app]
data_dir = "data"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/2"
cloud_backup = true
cloud_remote = "quark:/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    captured = {}

    class DummyExecutor:
        @staticmethod
        def shutdown(**_kwargs) -> None:
            return None

    class FakeService:
        def __init__(self, service_config, _logger, _shutdown) -> None:
            captured["config"] = service_config
            self.upload_executor = DummyExecutor()
            self.cloud_executor = DummyExecutor()

        @staticmethod
        def retry_cloud_only(_target):
            return {"processed": 1, "uploaded": 1, "failed": 0, "skipped": 0}

    monkeypatch.setattr("douyin_bili_recorder.cloud_retry.RecorderService", FakeService)
    manager = CloudRetryManager(config, logging.getLogger("test"))

    manager._run()

    assert captured["config"].targets[0].name == "anchor"
    assert manager.status()["result"]["uploaded"] == 1
