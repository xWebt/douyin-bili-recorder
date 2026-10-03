from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    ppid: int
    command: str


def parse_process_table(output: str) -> list[ProcessInfo]:
    processes: list[ProcessInfo] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split(None, 2)
        if len(fields) < 3:
            continue
        try:
            pid = int(fields[0])
            ppid = int(fields[1])
        except ValueError:
            continue
        processes.append(ProcessInfo(pid=pid, ppid=ppid, command=fields[2]))
    return processes


def read_process_table() -> list[ProcessInfo]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return []
    return parse_process_table(result.stdout)


def is_managed_process(command: str, data_dir: Path) -> bool:
    text = command.strip()
    lowered = text.lower()
    data_path = str(data_dir.expanduser().resolve()).lower()
    compact_data_path = data_path.replace(" ", "")
    compact_text = lowered.replace(" ", "")
    if "douyinbilirecorder.app/" in compact_text:
        return True
    if "douyinbilirecorder-old-" in compact_text:
        return True
    if "--internal-recorder" in lowered or "--internal-ui" in lowered:
        return True
    if "-m douyin_bili_recorder" in lowered:
        return True
    if "-m biliup server" in lowered and (data_path in lowered or compact_data_path in compact_text):
        return True
    tool_name = Path(lowered.split()[0]).name if lowered.split() else ""
    if tool_name in {"ffmpeg", "ffprobe"} and (
        data_path in lowered or "douyinbilirecorder" in compact_text
    ):
        return True
    if tool_name == "rclone" and "douyinbilirecorder" in compact_text:
        return True
    return False


def cleanup_stale_runtime_processes(
    data_dir: Path,
    *,
    current_pid: int | None = None,
    logger: logging.Logger | None = None,
    process_provider: Callable[[], Iterable[ProcessInfo]] = read_process_table,
    terminator: Callable[[int], None] | None = None,
) -> list[int]:
    processes = list(process_provider())
    protected = _protected_pids(processes, current_pid or os.getpid())
    targets = [
        process
        for process in processes
        if process.pid not in protected and is_managed_process(process.command, data_dir)
    ]
    target_pids = {process.pid for process in targets}
    targets.sort(key=lambda process: _process_priority(process.command))
    terminate = terminator or _terminate_process
    killed: list[int] = []
    for process in targets:
        if process.pid in target_pids:
            if logger is not None:
                logger.info("stopping stale recorder process %s: %s", process.pid, process.command)
            terminate(process.pid)
            killed.append(process.pid)
    return killed


def _protected_pids(processes: Iterable[ProcessInfo], current_pid: int) -> set[int]:
    parent_by_pid = {process.pid: process.ppid for process in processes}
    protected = {current_pid, os.getppid()}
    cursor = current_pid
    seen: set[int] = set()
    while cursor > 1 and cursor not in seen:
        seen.add(cursor)
        protected.add(cursor)
        cursor = parent_by_pid.get(cursor, 0)
    children: dict[int, list[int]] = {}
    for process in processes:
        children.setdefault(process.ppid, []).append(process.pid)
    pending = [current_pid]
    while pending:
        pid = pending.pop()
        for child in children.get(pid, []):
            if child in protected:
                continue
            protected.add(child)
            pending.append(child)
    return protected


def _process_priority(command: str) -> int:
    lowered = command.lower()
    if "--internal-ui" in lowered or "douyinbilirecorder.app/contents/macos" in lowered:
        return 0
    if "--internal-recorder" in lowered or "-m douyin_bili_recorder" in lowered:
        return 1
    if "biliup" in lowered and " server" in lowered:
        return 2
    return 3


def _terminate_process(pid: int) -> None:
    for sig, timeout in ((signal.SIGINT, 3), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                return
            time.sleep(0.1)
