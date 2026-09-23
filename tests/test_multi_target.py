from __future__ import annotations

import logging

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.pipeline import RecorderService


def test_session_ids_are_unique_for_similar_target_names(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[[targets]]
name = "anchor one"
url = "https://live.douyin.com/1"

[[targets]]
name = "anchor-one"
url = "https://live.douyin.com/2"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    service = RecorderService(config, logging.getLogger("test"))
    first = service._new_session(config.targets[0])
    second = service._new_session(config.targets[1])
    assert first.session_id != second.session_id
