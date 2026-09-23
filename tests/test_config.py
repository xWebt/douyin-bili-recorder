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

[storage]
video_dir = "videos"
late_threshold_minutes = 5
reconnect_grace_minutes = 15

[upload]
cookie_file = "secrets/cookies.json"
public = true

[[targets]]
name = "anchor"
url = "https://live.douyin.com/123"
record_mode = "monitor"
watch_mode = "manual"
collection_name = "anchor collection"

[[targets.schedule]]
days = [1, 3, 5]
start = "20:00"
end = "23:00"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.data_dir == tmp_path / "runtime"
    assert config.cookie_file == tmp_path / "secrets" / "cookies.json"
    assert config.targets[0].name == "anchor"
    assert config.video_dir == tmp_path / "videos"
    assert config.targets[0].public is True
    assert config.targets[0].record_mode == "monitor"
    assert config.targets[0].watch_mode == "manual"
    assert config.targets[0].collection_name == "anchor collection"
    assert config.targets[0].schedule[0].days == [1, 3, 5]
    assert config.quality == "origin"
    assert config.frame_rate == "source"


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



def test_load_config_rejects_invalid_recording_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[recording]
quality = "4k"
frame_rate = "120"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(config_path)
