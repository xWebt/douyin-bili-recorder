from __future__ import annotations

import argparse
import logging
import shutil
import signal
import sys
import threading
from pathlib import Path

from . import __version__
from .config import AppConfig, load_config
from .launchd import install_launchd, uninstall_launchd
from .logging_setup import configure_logging
from .pipeline import RecorderService

DEFAULT_CONFIG = """\
[app]
name = "douyin-bili-recorder"
timezone = "Asia/Shanghai"
data_dir = "data"
poll_interval_seconds = 30
max_reconnect_attempts = 5
reconnect_backoff_seconds = 15

[recording]
segment_time = "1h"
min_file_size_mb = 10
keep_original_files = true

[storage]
max_cache_gb = 10
video_dir = "~/Movies/DouyinBiliRecorder"
late_threshold_minutes = 5
reconnect_grace_minutes = 15

[upload]
biliup_bin = "biliup"
ffmpeg_bin = "ffmpeg"
ffprobe_bin = "ffprobe"
cookie_file = "cookies.json"
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
public = false
record_mode = "record"
watch_mode = "all_day"
collection_name = "example-anchor"
collection_id = ""
title_template = "{name}｜{start_date} {start_time} 开播｜{room_title}"
tags = ["直播录像", "抖音"]
tid = 171
copyright = 2
source = ""

[[targets.schedule]]
days = [1, 3, 5]
start = "20:00"
end = "23:00"
enabled = true
"""


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init-config":
        return command_init_config(args)
    if args.command == "version":
        print(__version__)
        return 0

    try:
        config = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    logger = configure_logging(config)
    if args.command == "doctor":
        return command_doctor(config, logger)
    if args.command == "status":
        return command_status(config, logger)
    if args.command == "recover":
        service = RecorderService(config, logger)
        service.recover_pending()
        return 0
    if args.command == "once":
        service = RecorderService(config, logger)
        recorded = service.run_once(args.target)
        return 0 if recorded else 3
    if args.command == "run":
        return command_run(config, logger)
    if args.command == "install-launchd":
        destination = install_launchd(config, load=args.load)
        print(destination)
        return 0
    if args.command == "uninstall-launchd":
        uninstall_launchd(config, unload=not args.keep_loaded)
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="douyin-recorder")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-config", help="create a starter TOML configuration")
    init_parser.add_argument("--output", default="config.toml")
    init_parser.add_argument("--force", action="store_true")

    version_parser = subparsers.add_parser("version", help="print package version")
    version_parser.set_defaults(command="version")

    for name, help_text in (
        ("doctor", "check local dependencies and configuration"),
        ("status", "print known sessions"),
        ("recover", "recover unfinished sessions"),
        ("run", "run the long-lived watcher and uploader"),
        ("install-launchd", "write a launchd agent (optionally load it)"),
        ("uninstall-launchd", "remove the launchd agent"),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument("--config", default="config.toml")
        if name == "install-launchd":
            command_parser.add_argument("--load", action="store_true")
        if name == "uninstall-launchd":
            command_parser.add_argument("--keep-loaded", action="store_true")

    once_parser = subparsers.add_parser("once", help="run one target cycle")
    once_parser.add_argument("--config", default="config.toml")
    once_parser.add_argument("--target")
    return parser


def command_init_config(args: argparse.Namespace) -> int:
    destination = Path(args.output).expanduser().resolve()
    if destination.exists() and not args.force:
        print(f"config already exists: {destination}", file=sys.stderr)
        return 2
    destination.write_text(DEFAULT_CONFIG, encoding="utf-8")
    print(destination)
    return 0


def command_doctor(config: AppConfig, logger: logging.Logger) -> int:
    failed = False
    checks = {
        "biliup": config.biliup_bin,
        "ffmpeg": config.ffmpeg_bin,
        "ffprobe": config.ffprobe_bin,
    }
    for label, executable in checks.items():
        resolved = shutil.which(executable)
        if resolved:
            print(f"OK   {label}: {resolved}")
        else:
            failed = True
            print(f"FAIL {label}: executable not found: {executable}")

    if config.cookie_file.exists():
        print(f"OK   cookies: {config.cookie_file}")
    else:
        failed = True
        print(f"FAIL cookies: missing {config.cookie_file}")

    if config.targets:
        print(f"OK   targets: {len(config.targets)} configured")
    else:
        failed = True
        print("FAIL targets: none configured")

    for target in config.targets:
        print(f"     target {target.name}: {target.url}")
    return 1 if failed else 0


def command_status(config: AppConfig, logger: logging.Logger) -> int:
    service = RecorderService(config, logger)
    records = service.status()
    if not records:
        print("no sessions")
        return 0
    for item in records:
        print(
            f"{item.session_id}\t{item.status}\t"
            f"{item.detected_start_iso or '-'}\t{item.bvid or '-'}\t{item.title or '-'}"
        )
    return 0


def command_run(config: AppConfig, logger: logging.Logger) -> int:
    shutdown = threading.Event()
    service = RecorderService(config, logger, shutdown)

    def stop(_signum, _frame) -> None:
        logger.info("shutdown signal received")
        service.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    service.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
