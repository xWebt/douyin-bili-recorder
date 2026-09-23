from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class UploadSample:
    at: float
    bytes_out: int


class UploadProgressStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "ui" / "upload-progress.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".upload-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class UploadProgressSampler:
    def __init__(self, store: UploadProgressStore, logger) -> None:
        self.store = store
        self.logger = logger
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(
        self,
        media_path: Path,
        *,
        target_name: str,
        title: str,
        part_index: int,
        total_bytes: int,
    ) -> None:
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"upload-progress-{part_index}",
            args=(media_path, target_name, title, part_index, total_bytes),
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, message: str = "上传结束", bvid: str | None = None) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._thread:
            previous = self.store.load()
            previous.update(
                {
                    "available": True,
                    "message": message,
                    "percent": 100 if bvid else previous.get("percent", 0),
                    "bvid": bvid or previous.get("bvid"),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            self.store.save(previous)
        self._thread = None

    def _run(
        self,
        media_path: Path,
        target_name: str,
        title: str,
        part_index: int,
        total_bytes: int,
    ) -> None:
        previous: UploadSample | None = None
        last_pid = 0
        while not self._stop.is_set():
            pid = self._pid_for_path(media_path)
            if not pid:
                time.sleep(0.5)
                continue
            sample = self._sample(pid)
            if sample is None:
                time.sleep(0.5)
                continue
            speed = 0.0
            if previous is not None and pid == last_pid and sample.at > previous.at:
                speed = max(0.0, (sample.bytes_out - previous.bytes_out) / (sample.at - previous.at))
            previous = sample
            last_pid = pid
            uploaded = min(sample.bytes_out, total_bytes)
            percent = min(99.9, uploaded / total_bytes * 100) if total_bytes else 0.0
            eta = int((total_bytes - uploaded) / speed) if speed > 0 and uploaded < total_bytes else None
            self.store.save(
                {
                    "available": True,
                    "message": "上传中",
                    "target": target_name,
                    "part": part_index,
                    "title": title,
                    "path": str(media_path),
                    "total_bytes": total_bytes,
                    "uploaded_bytes": uploaded,
                    "percent": percent,
                    "speed_bytes": speed,
                    "eta_seconds": eta,
                    "bvid": None,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            time.sleep(0.5)

    def _pid_for_path(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            result = subprocess.run(
                ["lsof", "-t", str(path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except OSError:
            return 0
        for line in result.stdout.splitlines():
            try:
                return int(line.strip())
            except ValueError:
                continue
        return 0

    def _sample(self, pid: int) -> UploadSample | None:
        try:
            result = subprocess.run(
                ["nettop", "-n", "-P", "-L", "1", "-s", "1", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
        except OSError:
            return None
        for line in reversed(result.stdout.splitlines()):
            fields = line.strip().split(",")
            if len(fields) < 7 or "DouyinBili" not in fields[1]:
                continue
            try:
                clock = datetime.strptime(fields[0], "%H:%M:%S.%f")
                instant = datetime.combine(datetime.today(), clock.time()).timestamp()
                return UploadSample(at=instant, bytes_out=int(fields[5]))
            except (ValueError, IndexError):
                continue
        return None
