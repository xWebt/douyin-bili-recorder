from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from pathlib import Path

from .models import SessionRecord


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return value or "target"


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        path = self.root / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def state_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def save(self, session: SessionRecord) -> None:
        path = self.state_path(session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=".session-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load(self, session_id: str) -> SessionRecord:
        with self.state_path(session_id).open("r", encoding="utf-8") as handle:
            return SessionRecord.from_dict(json.load(handle))

    def all(self) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for path in sorted(self.root.glob("*/session.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    records.append(SessionRecord.from_dict(json.load(handle)))
            except (OSError, ValueError, KeyError):
                continue
        return records

    def delete(self, session_id: str) -> None:
        import shutil

        path = self.root / session_id
        if path.exists():
            shutil.rmtree(path)


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False
        self._fd = -1

    def __enter__(self) -> SingleInstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self._fd)
            self._fd = -1
            raise RuntimeError(f"Another recorder process is already running: {self.path}") from exc
        os.ftruncate(self._fd, 0)
        os.write(self._fd, str(os.getpid()).encode("utf-8"))
        os.fsync(self._fd)
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.acquired:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = -1
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False
