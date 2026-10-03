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
import errno
from typing import Iterable


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    lines: list[str]
    cancelled: bool = False
    timed_out: bool = False


@dataclass(slots=True)
class RunningProcess:
    process: subprocess.Popen[str]
    lines: deque[str]
    reader: threading.Thread
    reaper: threading.Thread

    def group_alive(self) -> bool:
        try:
            os.killpg(self.process.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

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
        if not _process_group_exists(self.process.pid):
            self.process.poll()
            return
        terminate_process_group(self.process.pid)
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            pass


def terminate_process_group(pid: int, *, interrupt_timeout: float = 5.0,
                          term_timeout: float = 5.0, kill_timeout: float = 2.0) -> bool:
    """Escalate SIGINT → SIGTERM → SIGKILL until the process group is gone."""

    for sig, timeout in (
        (signal.SIGINT, interrupt_timeout),
        (signal.SIGTERM, term_timeout),
        (signal.SIGKILL, kill_timeout),
    ):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if not _process_group_exists(pid):
                return True
            time.sleep(0.1)
    return not _process_group_exists(pid)


def _process_group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:  # pragma: no cover - defensive
        return exc.errno != errno.ESRCH
    return True


class ChildProcessRegistry:
    """Tracks every child process so shutdown can reap them all."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[str]] = {}

    def register(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes[process.pid] = process

    def unregister(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes.pop(process.pid, None)

    def active(self) -> list[subprocess.Popen[str]]:
        with self._lock:
            return list(self._processes.values())

    def terminate_all(self, *, keep: Iterable[subprocess.Popen[str]] = ()) -> list[int]:
        protected = {process.pid for process in keep}
        terminated: list[int] = []
        for process in self.active():
            if process.pid in protected:
                continue
            if process.poll() is not None:
                self.unregister(process)
                continue
            terminate_process_group(process.pid)
            terminated.append(process.pid)
            self.unregister(process)
        return terminated


SHARED_CHILD_PROCESSES = ChildProcessRegistry()


def terminate_all_children() -> list[int]:
    """Terminate every child process started through ``ProcessRunner``."""

    return SHARED_CHILD_PROCESSES.terminate_all()


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
        self.registry = SHARED_CHILD_PROCESSES

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
        self.registry.register(process)

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
            self.registry.unregister(process)

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
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult:
        running = self.start(args, cwd=cwd)
        started = time.monotonic()
        timed_out = False
        cancelled = False

        try:
            while running.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    self.logger.info("upload cancellation requested, terminating child process")
                    running.terminate()
                    cancelled = True
                    break
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
            cancelled=cancelled,
            timed_out=timed_out,
        )

    def terminate(self, process: subprocess.Popen[str]) -> None:
        if not _process_group_exists(process.pid):
            process.poll()
            return
        terminate_process_group(process.pid)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            pass

    def terminate_active(self) -> None:
        with self._lock:
            processes = list(self._active)
        for process in processes:
            self.terminate(process)
