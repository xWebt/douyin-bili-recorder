from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
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
    timed_out: bool = False


@dataclass(slots=True)
class RunningProcess:
    process: subprocess.Popen[str]
    lines: deque[str]
    reader: threading.Thread
    reaper: threading.Thread

    def poll(self) -> int | None:
        returncode = self.process.poll()
        if returncode is not None:
            self.reader.join(timeout=1)
        return returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def output(self) -> list[str]:
        return list(self.lines)

    def terminate(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGINT)
        except ProcessLookupError:
            return
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


class ProcessRunner:
    def __init__(
        self,
        logger: logging.Logger,
        shutdown_event: threading.Event,
        interrupt_event: threading.Event | None = None,
    ) -> None:
        self.logger = logger
        self.shutdown_event = shutdown_event
        self.interrupt_event = interrupt_event
        self._active: set[subprocess.Popen[str]] = set()
        self._lock = threading.Lock()

    def start(
        self,
        args: Iterable[str],
        *,
        cwd: Path | None = None,
    ) -> RunningProcess:
        command = [str(item) for item in args]
        if command and command[0] == "__INTERNAL_BILIUP__":
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--internal-biliup", *command[1:]]
            else:
                command = [sys.executable, "-m", "biliup", *command[1:]]
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
            self._active.add(process)

        lines: deque[str] = deque(maxlen=5000)

        def reader() -> None:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\n")
                lines.append(line)
                self.logger.info("child: %s", line)

        def reaper() -> None:
            process.wait()
            with self._lock:
                self._active.discard(process)

        reader_thread = threading.Thread(target=reader, name="process-output", daemon=True)
        reaper_thread = threading.Thread(target=reaper, name="process-reaper", daemon=True)
        reader_thread.start()
        reaper_thread.start()
        return RunningProcess(process, lines, reader_thread, reaper_thread)

    def run(
        self,
        args: Iterable[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: int | None = None,
    ) -> ProcessResult:
        running = self.start(args, cwd=cwd)
        started = time.monotonic()
        timed_out = False

        try:
            while running.poll() is None:
                if self.shutdown_event.is_set() or (
                    self.interrupt_event is not None and self.interrupt_event.is_set()
                ):
                    self.logger.warning("shutdown requested, terminating child process")
                    running.terminate()
                    break
                if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                    self.logger.warning("child process timed out after %s seconds", timeout_seconds)
                    running.terminate()
                    timed_out = True
                    break
                time.sleep(0.25)
        finally:
            running.wait()
            running.reader.join(timeout=2)

        return ProcessResult(
            returncode=running.process.returncode,
            lines=running.output(),
            timed_out=timed_out,
        )

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
            processes = list(self._active)
        for process in processes:
            self.terminate(process)
