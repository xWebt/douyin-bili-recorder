from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    lines: list[str]


class ProcessRunner:
    def __init__(self, logger: logging.Logger, shutdown_event: threading.Event) -> None:
        self.logger = logger
        self.shutdown_event = shutdown_event
        self._active: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def run(
        self,
        args: Iterable[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: int | None = None,
    ) -> ProcessResult:
        command = [str(item) for item in args]
        if command and command[0] == "__INTERNAL_BILIUP__":
            command = [sys.executable, "--internal-biliup", *command[1:]]
        self.logger.info("running command: %s", " ".join(command))
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        with self._lock:
            self._active = process

        lines: deque[str] = deque(maxlen=5000)

        def reader() -> None:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\n")
                lines.append(line)
                self.logger.info("child: %s", line)

        thread = threading.Thread(target=reader, name="process-output", daemon=True)
        thread.start()
        started = time.monotonic()

        try:
            while process.poll() is None:
                if self.shutdown_event.is_set():
                    self.logger.warning("shutdown requested, terminating child process")
                    self.terminate(process)
                    break
                if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                    self.logger.warning("child process timed out after %s seconds", timeout_seconds)
                    self.terminate(process)
                    break
                time.sleep(0.25)
        finally:
            process.wait()
            thread.join(timeout=2)
            with self._lock:
                self._active = None

        return ProcessResult(returncode=process.returncode, lines=list(lines))

    def terminate(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def terminate_active(self) -> None:
        with self._lock:
            process = self._active
        if process is not None:
            self.terminate(process)
