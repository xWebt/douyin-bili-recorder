from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import time
from pathlib import Path


class OpenListManager:
    def __init__(self, root: Path, logger: logging.Logger) -> None:
        self.root = root
        self.logger = logger
        self.binary = root / "tools" / "openlist" / "openlist"
        self.data_dir = root / "openlist-data"
        self.log_path = root / "data" / "logs" / "openlist-managed.log"
        self._process: subprocess.Popen[object] | None = None

    def is_ready(self, timeout: float = 0.3) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", 5244), timeout=timeout):
                return True
        except OSError:
            return False

    def ensure_running(self, timeout_seconds: float = 10.0) -> bool:
        if self.is_ready():
            return True
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            self.logger.warning("OpenList executable not found: %s", self.binary)
            return False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = self.log_path.open("a", encoding="utf-8")
        self._process = subprocess.Popen(
            [str(self.binary), "--data", str(self.data_dir), "server"],
            cwd=str(self.root),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_ready():
                self.logger.info("OpenList is ready on 127.0.0.1:5244")
                return True
            if self._process.poll() is not None:
                self.logger.warning("OpenList exited with code %s", self._process.returncode)
                self._process = None
                return False
            time.sleep(0.25)
        self.logger.warning("OpenList did not become ready within %.1f seconds", timeout_seconds)
        return False

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
