from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass(slots=True)
class BandwidthSnapshot:
    bilibili_active: int
    cloud_active: int
    cloud_limit_kbps: int
    cloud_max_concurrency: int
    bilibili_priority: bool


class BandwidthScheduler:
    """Global bandwidth policy: Bilibili uploads win, cloud uploads yield.

    The scheduler only coordinates; the actual throttling is applied by the
    cloud drivers (``rclone --bwlimit``, token bucket for HTTP drivers).
    """

    def __init__(
        self,
        *,
        cloud_limit_kbps: int = 0,
        cloud_max_concurrency: int = 2,
        bilibili_priority: bool = True,
    ) -> None:
        self._lock = threading.Lock()
        self._bilibili_active = 0
        self._cloud_active = 0
        self._cloud_limit_kbps = max(0, int(cloud_limit_kbps))
        self._cloud_max_concurrency = max(1, int(cloud_max_concurrency))
        self._bilibili_priority = bool(bilibili_priority)

    def configure(
        self,
        *,
        cloud_limit_kbps: int | None = None,
        cloud_max_concurrency: int | None = None,
        bilibili_priority: bool | None = None,
    ) -> None:
        with self._lock:
            if cloud_limit_kbps is not None:
                self._cloud_limit_kbps = max(0, int(cloud_limit_kbps))
            if cloud_max_concurrency is not None:
                self._cloud_max_concurrency = max(1, int(cloud_max_concurrency))
            if bilibili_priority is not None:
                self._bilibili_priority = bool(bilibili_priority)

    @contextmanager
    def bilibili_upload(self) -> Iterator[None]:
        with self._lock:
            self._bilibili_active += 1
        try:
            yield
        finally:
            with self._lock:
                self._bilibili_active = max(0, self._bilibili_active - 1)

    @contextmanager
    def cloud_slot(self) -> Iterator[None]:
        """Serialize cloud uploads according to the configured concurrency."""

        while True:
            with self._lock:
                limit = self._cloud_max_concurrency
                if self._cloud_active < limit:
                    self._cloud_active += 1
                    break
            time.sleep(0.25)
        try:
            yield
        finally:
            with self._lock:
                self._cloud_active = max(0, self._cloud_active - 1)

    def cloud_limit_kbps(self) -> int:
        """Effective per-upload limit for cloud transfers."""
        with self._lock:
            return self._cloud_limit_kbps

    def snapshot(self) -> BandwidthSnapshot:
        with self._lock:
            return BandwidthSnapshot(
                bilibili_active=self._bilibili_active,
                cloud_active=self._cloud_active,
                cloud_limit_kbps=self._cloud_limit_kbps,
                cloud_max_concurrency=self._cloud_max_concurrency,
                bilibili_priority=self._bilibili_priority,
            )


BANDWIDTH = BandwidthScheduler()


def configure_from_state(state: dict) -> None:
    """Apply UI runtime settings to the global scheduler."""

    def _int(key: str, default: int) -> int:
        try:
            return int(state.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    BANDWIDTH.configure(
        cloud_limit_kbps=_int("cloud_bandwidth_limit_kbps", 0),
        cloud_max_concurrency=_int("cloud_max_concurrency", 1),
        bilibili_priority=bool(state.get("bilibili_priority", True)),
    )
