from __future__ import annotations

import logging
from pathlib import Path

from .models import SessionStatus
from .state import SessionStore


class StorageGuard:
    def __init__(self, sessions_dir: Path, logger: logging.Logger) -> None:
        self.sessions_dir = sessions_dir
        self.store = SessionStore(sessions_dir)
        self.logger = logger

    def usage_bytes(self) -> int:
        total = 0
        if not self.sessions_dir.exists():
            return total
        for path in self.sessions_dir.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def usage_gb(self) -> float:
        return round(self.usage_bytes() / (1024**3), 2)

    def enforce_limit(self, max_cache_gb: int) -> float:
        limit = max_cache_gb * 1024**3
        usage = self.usage_bytes()
        if usage <= limit:
            return round(usage / (1024**3), 2)

        uploaded = [
            session
            for session in self.store.all()
            if session.status == SessionStatus.UPLOADED
        ]
        uploaded.sort(key=lambda item: item.ended_epoch or item.created_epoch)
        for session in uploaded:
            if usage <= limit:
                break
            session_dir = self.sessions_dir / session.session_id
            size = _directory_size(session_dir)
            self.logger.info("cache limit reached, deleting uploaded session %s", session.session_id)
            self.store.delete(session.session_id)
            usage = max(0, usage - size)

        if usage > limit:
            self.logger.warning(
                "cache usage %.2f GB exceeds limit %s GB and no uploaded session can be removed",
                usage / (1024**3),
                max_cache_gb,
            )
        return round(usage / (1024**3), 2)

    def can_start_session(self, max_cache_gb: int) -> bool:
        return self.usage_bytes() < max_cache_gb * 1024**3


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
