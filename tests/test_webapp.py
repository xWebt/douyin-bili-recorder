from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.paths import target_key
from douyin_bili_recorder.webapp import _ensure_service_running, _start_target


class FakeStateStore:
    def load(self) -> dict:
        return {
            "max_cache_gb": 10,
            "targets": [{"name": "anchor", "enabled": False}],
        }

    def save(self, state: dict) -> dict:
        self.state = state
        return state

    def render_runtime_config(self, _state: dict) -> None:
        return None


class FakeController:
    def __init__(self) -> None:
        self.started = False

    def status(self, _limit: int) -> dict[str, bool]:
        return {"running": self.started}

    def start(self) -> dict[str, bool]:
        self.started = True
        return {"running": True}


def _config(tmp_path: Path):
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
    return load_config(config_path)


def test_retry_path_starts_stopped_service(tmp_path: Path) -> None:
    config = _config(tmp_path)
    controller = FakeController()

    _ensure_service_running(config, FakeStateStore(), controller)  # type: ignore[arg-type]

    assert controller.started is True


def test_start_target_enables_target_and_queues_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = FakeStateStore()
    controller = FakeController()

    result = _start_target(config, store, controller, "anchor")  # type: ignore[arg-type]

    assert result["enabled"] is True
    assert controller.started is True
    assert (config.data_dir / "ui" / "manual" / f"{target_key('anchor')}.request").exists()
