from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from ..config import AppConfig
from ..process import ProcessRunner


class CloudDriverError(RuntimeError):
    pass


@dataclass(slots=True)
class DriverCapabilities:
    """What a driver can do, surfaced to the UI and the scheduler."""

    chunked: bool = False
    concurrent_parts: int = 1
    direct_api: bool = False
    bandwidth_limit: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "chunked": self.chunked,
            "concurrent_parts": self.concurrent_parts,
            "direct_api": self.direct_api,
            "bandwidth_limit": self.bandwidth_limit,
            "notes": self.notes,
        }


@dataclass(slots=True)
class UploadOutcome:
    remote_paths: list[str]
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DriverContext:
    config: AppConfig
    runner: ProcessRunner
    logger: logging.Logger


@runtime_checkable
class CloudDriver(Protocol):
    name: str
    capabilities: DriverCapabilities

    def ensure_dir(self, remote_dir: str, cancel_event: threading.Event) -> None: ...

    def upload(
        self,
        local_path: Path,
        remote_path: str,
        cancel_event: threading.Event,
    ) -> UploadOutcome: ...

    def probe(self, remote: str) -> list[str]: ...


DriverFactory = Callable[[str, DriverContext], CloudDriver | None]

_REGISTRY: dict[str, list[DriverFactory]] = {}
_REGISTRY_LOCK = threading.Lock()


def register_driver(provider: str, factory: DriverFactory, *, priority: int = 0) -> None:
    """Register a driver factory for one provider key (``quark``, ``baidu``...)."""

    key = provider.strip().lower() or "custom"
    with _REGISTRY_LOCK:
        factories = _REGISTRY.setdefault(key, [])
        factories.append(factory)
        factories.sort(key=lambda item: priority, reverse=True)


def _factories(provider: str) -> list[DriverFactory]:
    key = provider.strip().lower() or "custom"
    with _REGISTRY_LOCK:
        return list(_REGISTRY.get(key, []))


def detect_provider(remote: str) -> str:
    """Guess the cloud provider from an rclone remote name."""

    name = remote.split(":", 1)[0].strip().lower()
    if "quark" in name or name.startswith("uc"):
        return "quark"
    if "baidu" in name or "pan" in name:
        return "baidu"
    return "custom"


def create_driver(provider: str, remote: str, context: DriverContext) -> CloudDriver:
    """Pick the best driver for ``provider`` and fall back to generic drivers."""

    for factory in _factories(provider):
        driver = factory(remote, context)
        if driver is not None:
            return driver
    for factory in _factories("custom"):
        driver = factory(remote, context)
        if driver is not None:
            return driver
    raise CloudDriverError(f"no cloud driver available for provider={provider!r}")
