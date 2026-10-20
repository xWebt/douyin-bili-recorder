from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.pipeline import RecorderService


class FakeRecorderProcess:
    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"
poll_interval_seconds = 5

[storage]
video_dir = "videos"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
enabled = true
watch_mode = "all_day"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_target_loop_does_not_overwrite_space_error(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    target = config.targets[0]
    service.record_and_upload = lambda _target: False
    service._set_target_status(target, "error", "缓存空间不足：请处理失败分段")

    worker = threading.Thread(target=service._target_loop, args=(target,))
    worker.start()
    time.sleep(0.7)
    status = service.target_status.load_all().get("anchor", {})
    service.shutdown_event.set()
    worker.join(timeout=5)

    assert status.get("state") == "error"
    assert "缓存空间不足" in str(status.get("message"))
    assert not worker.is_alive()


def test_terminate_active_recorder_terminates_and_unregisters(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    process = FakeRecorderProcess()
    service._register_recorder("anchor", process)  # type: ignore[arg-type]

    service._terminate_active_recorder("anchor")

    assert process.terminated is True
    assert service._active_recorders == {}
