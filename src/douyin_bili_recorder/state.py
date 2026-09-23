from __future__ import annotations

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

    def __enter__(self) -> SingleInstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                break
            except FileExistsError as exc:
                if self._remove_stale_lock():
                    continue
                raise RuntimeError(f"Another recorder process is already running: {self.path}") from exc
        else:
            raise RuntimeError(f"Unable to acquire recorder lock: {self.path}")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        self.acquired = True
        return self

    def _remove_stale_lock(self) -> bool:
        try:
            pid = int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = -1
        if pid > 0:
            try:
                os.kill(pid, 0)
                return False
            except ProcessLookupError:
                pass
            except PermissionError:
                return False
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return True

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False
