from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .paths import target_key


class TargetStatusStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "ui" / "target-status"

    def update(self, name: str, state: str, message: str = "", **extra: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": name,
            "state": state,
            "message": message,
            "updated_at": int(time.time()),
        }
        payload.update(extra)
        path = self._path(name)
        fd, temp_name = tempfile.mkstemp(prefix=".target-status-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load_all(self) -> dict[str, dict[str, Any]]:
        statuses: dict[str, dict[str, Any]] = {}
        if not self.root.exists():
            return statuses
        for path in sorted(self.root.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                continue
            name = str(payload.get("name", "")).strip()
            if name:
                statuses[name] = payload
        return statuses

    def clear(self, name: str) -> None:
        path = self._path(name)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _path(self, name: str) -> Path:
        return self.root / f"{target_key(name)}.json"
