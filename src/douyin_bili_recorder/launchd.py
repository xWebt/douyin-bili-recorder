from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .config import AppConfig


def plist_path(config: AppConfig) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{config.launchd_label}.plist"


def build_launchd_payload(config: AppConfig) -> dict[str, object]:
    return {
        "Label": config.launchd_label,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "douyin_bili_recorder",
            "run",
            "--config",
            str(config.config_path),
        ],
        "WorkingDirectory": str(config.config_path.parent),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(config.logs_dir / "launchd.out.log"),
        "StandardErrorPath": str(config.logs_dir / "launchd.err.log"),
    }


def install_launchd(config: AppConfig, *, load: bool = False) -> Path:
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    destination = plist_path(config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        plistlib.dump(build_launchd_payload(config), handle, sort_keys=False)
    if load:
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)],
            check=True,
        )
    return destination


def uninstall_launchd(config: AppConfig, *, unload: bool = True) -> None:
    destination = plist_path(config)
    if unload and destination.exists():
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(destination)],
            check=False,
        )
    destination.unlink(missing_ok=True)
