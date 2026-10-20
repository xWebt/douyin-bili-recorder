from __future__ import annotations

from .baidu import baidu_factory
from .driver import (
    CloudDriver,
    CloudDriverError,
    DriverCapabilities,
    DriverContext,
    UploadOutcome,
    create_driver,
    detect_provider,
    register_driver,
)
from .openlist import OpenListDriver
from .quark import quark_factory
from .quark_sync import quark_sync_factory
from .rclone import RcloneDriver

# Provider-specific CLIs win; OpenList is the standard local bridge; plain
# rclone is the generic fallback.
register_driver("quark", quark_factory, priority=10)
register_driver("quark", quark_sync_factory, priority=20)
register_driver("baidu", baidu_factory, priority=10)


def _openlist_factory(remote: str, context: DriverContext) -> OpenListDriver:
    return OpenListDriver(remote, context)


register_driver("custom", _openlist_factory, priority=0)
register_driver("quark", _openlist_factory, priority=0)
register_driver("baidu", _openlist_factory, priority=0)
register_driver("custom", lambda remote, context: RcloneDriver(remote, context), priority=-1)

__all__ = [
    "CloudDriver",
    "CloudDriverError",
    "DriverCapabilities",
    "DriverContext",
    "OpenListDriver",
    "RcloneDriver",
    "UploadOutcome",
    "create_driver",
    "detect_provider",
]
