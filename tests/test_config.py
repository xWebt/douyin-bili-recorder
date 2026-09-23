from __future__ import annotations

from pathlib import Path

import pytest

from douyin_bili_recorder.config import ConfigError, load_config


def test_load_config_resolves_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "runtime"
poll_interval_seconds = 20

[recording]
segment_time = "1h"

[upload]
cookie_file = "secrets/cookies.json"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.data_dir == tmp_path / "runtime"
    assert config.cookie_file == tmp_path / "secrets" / "cookies.json"
    assert config.targets[0].name == "anchor"


def test_load_config_rejects_duplicate_names(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "runtime"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/2"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(config_path)
