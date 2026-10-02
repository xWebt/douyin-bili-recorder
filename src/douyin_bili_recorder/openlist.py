from __future__ import annotations

import json
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
        self.owner_pid_path = root / "data" / "openlist-owned.pid"
        self._process: subprocess.Popen[object] | None = None

    def is_ready(self, timeout: float = 0.3) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", 5244), timeout=timeout):
                return True
        except OSError:
            return False

    def ensure_running(self, timeout_seconds: float = 10.0) -> bool:
        if self.is_ready():
            self.logger.info("reusing existing OpenList listener on 127.0.0.1:5244")
            return True
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            self.logger.warning("OpenList executable not found: %s", self.binary)
            return False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.owner_pid_path.parent.mkdir(parents=True, exist_ok=True)
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
        self.owner_pid_path.write_text(
            json.dumps({"pid": self._process.pid, "binary": str(self.binary)}),
            encoding="utf-8",
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_ready():
                self.logger.info("OpenList is ready on 127.0.0.1:5244")
                return True
            if self._process.poll() is not None:
                self.logger.warning("OpenList exited with code %s", self._process.returncode)
                self._process = None
                self.owner_pid_path.unlink(missing_ok=True)
                return False
            time.sleep(0.25)
        self.logger.warning("OpenList did not become ready within %.1f seconds", timeout_seconds)
        return False

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            self._stop_process(process.pid)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

        self._stop_pid_from_owner_file()
        listener_pid = self._owned_listener_pid()
        if listener_pid:
            self._stop_process(listener_pid)
        self.owner_pid_path.unlink(missing_ok=True)

    def _stop_existing_owned(self) -> bool:
        owner_pid = self._owner_pid()
        if owner_pid:
            self.logger.info("stopping stale owned OpenList process %s", owner_pid)
            self._stop_process(owner_pid)
            self.owner_pid_path.unlink(missing_ok=True)
            return True

        listener_pid = self._owned_listener_pid()
        if listener_pid:
            self.logger.info("stopping stale OpenList listener %s from the app directory", listener_pid)
            self._stop_process(listener_pid)
            self.owner_pid_path.unlink(missing_ok=True)
            return True
        return False

    def _stop_pid_from_owner_file(self) -> None:
        pid = self._owner_pid()
        if pid:
            self._stop_process(pid)
        self.owner_pid_path.unlink(missing_ok=True)

    def _owner_pid(self) -> int:
        try:
            payload = json.loads(self.owner_pid_path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0))
            binary = str(payload.get("binary", ""))
        except (OSError, ValueError, TypeError):
            self.owner_pid_path.unlink(missing_ok=True)
            return 0
        if pid > 0 and binary and self._pid_matches(pid, binary):
            return pid
        self.owner_pid_path.unlink(missing_ok=True)
        return 0

    def _owned_listener_pid(self) -> int:
        for executable in ("/usr/sbin/lsof", "lsof"):
            try:
                result = subprocess.run(
                    [executable, "-nP", "-iTCP:5244", "-sTCP:LISTEN", "-t"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=3,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            for value in result.stdout.split():
                try:
                    pid = int(value)
                except ValueError:
                    continue
                if self._pid_matches(pid, str(self.binary)):
                    return pid
            return 0
        return 0

    def _pid_matches(self, pid: int, binary: str) -> bool:
        command = self._command_for_pid(pid)
        return bool(command and binary in command)

    @staticmethod
    def _command_for_pid(pid: int) -> str:
        for executable in ("/usr/sbin/lsof", "lsof"):
            try:
                result = subprocess.run(
                    [executable, "-p", str(pid), "-a", "-d", "txt", "-Fn"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=3,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            for line in result.stdout.splitlines():
                if line.startswith("n") and len(line) > 1:
                    return line[1:].strip()
            return ""
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout.strip()

    def _wait_until_stopped(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self.is_ready():
                return True
            time.sleep(0.1)
        return False

    def _stop_process(self, pid: int) -> None:
        for sig, timeout_seconds in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 1.0)):
            if not self._pid_alive(pid):
                return
            self._signal_process(pid, sig)
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline and self._pid_alive(pid):
                time.sleep(0.1)
        if self._pid_alive(pid):
            self.logger.warning("OpenList process %s did not exit after SIGKILL", pid)

    @staticmethod
    def _signal_process(pid: int, sig: int) -> None:
        try:
            os.killpg(pid, sig)
            return
        except (PermissionError, ProcessLookupError):
            pass
        try:
            os.kill(pid, sig)
        except (PermissionError, ProcessLookupError):
            pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
