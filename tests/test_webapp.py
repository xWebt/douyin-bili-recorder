from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.webapp import _ensure_service_running


class FakeStateStore:
    def load(self) -> dict[str, int]:
        return {"max_cache_gb": 10}


class FakeController:
    def __init__(self) -> None:
        self.started = False

    def status(self, _limit: int) -> dict[str, bool]:
        return {"running": self.started}

    def start(self) -> dict[str, bool]:
        self.started = True
        return {"running": True}


def test_retry_path_starts_stopped_service(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[upload]
cookie_file = "cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    controller = FakeController()

    _ensure_service_running(config, FakeStateStore(), controller)  # type: ignore[arg-type]

    assert controller.started is True
