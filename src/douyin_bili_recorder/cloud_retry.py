from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .config import AppConfig
from .config import load_config
from .pipeline import RecorderService


class CloudRetryManager:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._target_name = ""
        self._started_at = 0
        self._result: dict[str, int] | None = None
        self._error = ""

    def start(self, target_name: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._status_unlocked()
            self._stop_event = threading.Event()
            self._target_name = str(target_name or "")
            self._started_at = int(time.time())
            self._result = None
            self._error = ""
            self._thread = threading.Thread(
                target=self._run,
                name="cloud-retry",
                daemon=True,
            )
            self._thread.start()
            return self._status_unlocked()

    def stop(self) -> dict[str, Any]:
        thread = self._thread
        if thread is None or not thread.is_alive():
            return self.status()
        self._stop_event.set()
        thread.join(timeout=10)
        with self._lock:
            if self._thread is thread and not thread.is_alive():
                self._thread = None
            return self._status_unlocked()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def _run(self) -> None:
        runtime_config = load_config(self.config.data_dir / "ui" / "runtime-config.toml")
        service = RecorderService(runtime_config, self.logger, self._stop_event)
        try:
            result = service.retry_cloud_only(self._target_name or None)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._error = str(exc)
            self.logger.exception("cloud-only retry failed")
        else:
            with self._lock:
                self._result = result
        finally:
            service.upload_executor.shutdown(wait=False, cancel_futures=True)
            service.cloud_executor.shutdown(wait=False, cancel_futures=True)
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _status_unlocked(self) -> dict[str, Any]:
        thread = self._thread
        return {
            "running": bool(thread is not None and thread.is_alive()),
            "target": self._target_name,
            "started_at": self._started_at or None,
            "result": self._result,
            "error": self._error,
        }
