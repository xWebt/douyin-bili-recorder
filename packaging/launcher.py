from __future__ import annotations

import argparse
import sys
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.desktop import run_desktop


def main() -> int:
    if "--internal-ui" in sys.argv:
        sys.argv.remove("--internal-ui")
        import argparse
        import uvicorn

        from douyin_bili_recorder.webapp import create_app

        parser = argparse.ArgumentParser(prog="DouyinBiliRecorderUI")
        parser.add_argument("--config", required=True)
        parser.add_argument("--port", type=int, default=8765)
        args = parser.parse_args()
        uvicorn.run(create_app(load_config(args.config)), host="127.0.0.1", port=args.port, log_level="info")
        return 0
    if "--internal-recorder" in sys.argv:
        sys.argv.remove("--internal-recorder")
        from douyin_bili_recorder.cli import main as recorder_main

        return recorder_main()
    if "--internal-biliup" in sys.argv:
        sys.argv.remove("--internal-biliup")
        from stream_gears import main_loop

        main_loop()
        return 0

    parser = argparse.ArgumentParser(prog="DouyinBiliRecorder")
    parser.add_argument("--config")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    run_desktop(load_config(_resolve_config(args.config)), debug=args.debug)
    return 0


def _resolve_config(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    root = Path.home() / "Library" / "Application Support" / "DouyinBiliRecorder"
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "config.toml"
    if not config_path.exists():
        config_path.write_text(_packaged_config(root), encoding="utf-8")
    return config_path


def _packaged_config(root: Path) -> str:
    data_dir = root / "data"
    cookies = root / "cookies.json"
    return f'''[app]
name = "douyin-bili-recorder"
timezone = "Asia/Shanghai"
data_dir = "{data_dir}"
poll_interval_seconds = 30
max_reconnect_attempts = 5
reconnect_backoff_seconds = 15

[recording]
segment_time = "1h"
min_file_size_mb = 10
keep_original_files = true

[storage]
max_cache_gb = 10

[upload]
biliup_bin = "__INTERNAL_BILIUP__"
ffmpeg_bin = "ffmpeg"
ffprobe_bin = "ffprobe"
cookie_file = "{cookies}"
line = "bda2"
public = false
delete_after_upload = false
retry_count = 5
retry_backoff_seconds = 30

[launchd]
label = "com.webt.douyin-bili-recorder"

[[targets]]
name = "example-anchor"
url = "https://www.douyin.com/user/REPLACE_ME"
enabled = false
title_template = "{{name}}｜{{start_date}} {{start_time}} 开播｜{{room_title}}"
tags = ["直播录像", "抖音"]
tid = 171
copyright = 2
source = ""
'''


if __name__ == "__main__":
    raise SystemExit(main())
