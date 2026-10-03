from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .db import Database
from .models import MediaFile, SessionPart, SessionRecord
from .part_state import assert_part_transition, normalize_part_state


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return value or "target"


_SESSION_COLUMNS = (
    "session_id",
    "target_name",
    "target_url",
    "status",
    "created_epoch",
    "detected_start_epoch",
    "detected_start_iso",
    "ended_epoch",
    "room_title",
    "bvid",
    "title",
    "attempts",
    "error",
    "record_mode",
    "scheduled_start_epoch",
    "late",
    "late_minutes",
    "last_seen_live_epoch",
    "reconnect_count",
    "reconnect_seconds",
    "collection_id",
    "collection_status",
    "cloud_backup",
    "cloud_provider",
    "cloud_remote",
)

_PART_COLUMNS = (
    "session_id",
    "part_index",
    "status",
    "title",
    "path",
    "source_path",
    "danmaku_path",
    "size",
    "duration_seconds",
    "bvid",
    "uploaded_at",
    "error",
    "cloud_status",
    "cloud_error",
    "cloud_path",
    "cloud_uploaded_at",
    "cloud_attempts",
)

_RUNNING_JOB_STALE_SECONDS = 6 * 60 * 60


@dataclass(slots=True)
class UploadJob:
    job_key: str
    session_id: str
    part_index: int
    kind: str
    state: str
    attempts: int = 0
    fingerprint: str = ""
    bvid: str = ""
    remote_path: str = ""
    message: str = ""
    created_at: int = 0
    updated_at: int = 0

    @property
    def succeeded(self) -> bool:
        return self.state == "SUCCEEDED"


@dataclass(slots=True)
class UploadClaim:
    job: UploadJob
    claimed: bool
    reason: str = ""


def upload_job_key(kind: str, session_id: str, part_index: int) -> str:
    return f"{kind}:{session_id}:{part_index}"


def _row_to_job(row: sqlite3.Row) -> UploadJob:
    return UploadJob(
        job_key=str(row["job_key"]),
        session_id=str(row["session_id"]),
        part_index=int(row["part_index"]),
        kind=str(row["kind"]),
        state=str(row["state"]),
        attempts=int(row["attempts"] or 0),
        fingerprint=str(row["fingerprint"] or ""),
        bvid=str(row["bvid"] or ""),
        remote_path=str(row["remote_path"] or ""),
        message=str(row["message"] or ""),
        created_at=int(row["created_at"] or 0),
        updated_at=int(row["updated_at"] or 0),
    )


def _session_params(session: SessionRecord) -> tuple[Any, ...]:
    return (
        session.session_id,
        session.target_name,
        session.target_url,
        str(session.status),
        int(session.created_epoch or 0),
        session.detected_start_epoch,
        session.detected_start_iso,
        session.ended_epoch,
        session.room_title,
        session.bvid,
        session.title,
        int(session.attempts or 0),
        session.error,
        session.record_mode,
        session.scheduled_start_epoch,
        1 if session.late else 0,
        int(session.late_minutes or 0),
        session.last_seen_live_epoch,
        int(session.reconnect_count or 0),
        int(session.reconnect_seconds or 0),
        session.collection_id,
        session.collection_status,
        1 if session.cloud_backup else 0,
        session.cloud_provider,
        session.cloud_remote,
    )


def _part_params(session_id: str, part: SessionPart) -> tuple[Any, ...]:
    return (
        session_id,
        int(part.index),
        normalize_part_state(part.status),
        part.title,
        part.path,
        part.source_path,
        part.danmaku_path,
        int(part.size or 0),
        part.duration_seconds,
        part.bvid,
        part.uploaded_at,
        part.error,
        part.cloud_status,
        part.cloud_error,
        part.cloud_path,
        part.cloud_uploaded_at,
        int(part.cloud_attempts or 0),
    )


def _file_params(session_id: str, item: MediaFile) -> tuple[Any, ...]:
    return (
        session_id,
        item.path,
        int(item.size or 0),
        item.duration_seconds,
        item.sha256,
        item.source,
        1 if item.uploaded else 0,
    )


class SessionStore:
    """SQLite-backed source of truth for sessions, parts and upload jobs.

    ``session.json`` is still written next to each session as a debugging and
    export snapshot, but it is no longer read back unless a database is created
    for the first time with legacy JSON already on disk.
    """

    DB_FILENAME = "recorder.sqlite3"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.root / self.DB_FILENAME)
        self.db.initialize()
        self._migrate_legacy_json()

    # ------------------------------------------------------------------ paths

    def session_dir(self, session_id: str) -> Path:
        path = self.root / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def state_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    # ------------------------------------------------------------------ reads

    def load(self, session_id: str) -> SessionRecord:
        with self.db.read() as connection:
            return self._load_with(connection, session_id)

    def all(self) -> list[SessionRecord]:
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created_epoch ASC, session_id ASC"
            ).fetchall()
            return [self._record_with(connection, row) for row in rows]

    def load_many(self, session_ids: list[str]) -> list[SessionRecord]:
        if not session_ids:
            return []
        placeholders = ",".join("?" for _ in session_ids)
        with self.db.read() as connection:
            rows = connection.execute(
                f"SELECT * FROM sessions WHERE session_id IN ({placeholders}) "
                "ORDER BY created_epoch ASC, session_id ASC",
                tuple(session_ids),
            ).fetchall()
            return [self._record_with(connection, row) for row in rows]

    def jobs_for_session(self, session_id: str) -> list[UploadJob]:
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM upload_jobs WHERE session_id = ? ORDER BY kind, part_index",
                (session_id,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def upload_job(self, job_key: str) -> UploadJob | None:
        with self.db.read() as connection:
            row = connection.execute(
                "SELECT * FROM upload_jobs WHERE job_key = ?", (job_key,)
            ).fetchone()
        return _row_to_job(row) if row is not None else None

    # ----------------------------------------------------------------- writes

    def save(self, session: SessionRecord) -> None:
        with self.db.transaction() as connection:
            self._write_with(connection, session)
        self._write_snapshot(session)

    def delete(self, session_id: str) -> None:
        import shutil

        with self.db.transaction() as connection:
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM upload_jobs WHERE session_id = ?", (session_id,))
        path = self.root / session_id
        if path.exists():
            shutil.rmtree(path)

    def update(
        self,
        session_id: str,
        mutator: Callable[[SessionRecord], None],
    ) -> SessionRecord:
        """Read-modify-write one session inside a single transaction."""

        with self.db.transaction() as connection:
            session = self._load_with(connection, session_id)
            mutator(session)
            self._write_with(connection, session)
        self._write_snapshot(session)
        return session

    def update_part(
        self,
        session_id: str,
        part_index: int,
        mutator: Callable[[SessionPart], None],
        *,
        session_mutator: Callable[[SessionRecord], None] | None = None,
    ) -> SessionPart | None:
        result: SessionPart | None = None

        def apply(session: SessionRecord) -> None:
            nonlocal result
            part = next((item for item in session.parts if item.index == part_index), None)
            if part is None:
                return
            mutator(part)
            if session_mutator is not None:
                session_mutator(session)
            result = part

        self.update(session_id, apply)
        return result

    def set_part_state(
        self,
        session_id: str,
        part_index: int,
        state: str,
        *,
        force: bool = False,
        error: str | None = None,
        **fields: Any,
    ) -> SessionPart | None:
        target = normalize_part_state(state)
        updated: SessionPart | None = None

        def apply(session: SessionRecord) -> None:
            nonlocal updated
            part = next((item for item in session.parts if item.index == part_index), None)
            if part is None:
                return
            if not force:
                assert_part_transition(part.status, target)
            part.status = target
            if error is not None:
                part.error = error
            for key, value in fields.items():
                setattr(part, key, value)
            updated = part

        self.update(session_id, apply)
        return updated

    # ------------------------------------------------------------- upload jobs

    def claim_upload_job(
        self,
        kind: str,
        session_id: str,
        part_index: int,
        *,
        fingerprint: str = "",
        stale_seconds: int = _RUNNING_JOB_STALE_SECONDS,
    ) -> UploadClaim:
        """Claim exclusive ownership of one upload action.

        ``claimed=False`` plus ``job.succeeded`` means the action already
        finished and must not run again. ``claimed=False`` without success means
        another worker holds a fresh claim.
        """

        job_key = upload_job_key(kind, session_id, part_index)
        now = int(time.time())
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM upload_jobs WHERE job_key = ?", (job_key,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO upload_jobs"
                    "(job_key, session_id, part_index, kind, state, attempts, fingerprint,"
                    " bvid, remote_path, message, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_key,
                        session_id,
                        int(part_index),
                        kind,
                        "RUNNING",
                        1,
                        fingerprint,
                        "",
                        "",
                        "",
                        now,
                        now,
                    ),
                )
                job = self.upload_job_with(connection, job_key)
                return UploadClaim(job=job, claimed=True, reason="claimed")

            existing = _row_to_job(row)
            if existing.succeeded:
                return UploadClaim(job=existing, claimed=False, reason="already-succeeded")
            running_fresh = (
                existing.state == "RUNNING"
                and stale_seconds > 0
                and now - existing.updated_at < stale_seconds
            )
            if running_fresh:
                return UploadClaim(job=existing, claimed=False, reason="already-running")
            connection.execute(
                "UPDATE upload_jobs SET state='RUNNING', attempts = attempts + 1,"
                " fingerprint = ?, message = '', updated_at = ? WHERE job_key = ?",
                (fingerprint or existing.fingerprint, now, job_key),
            )
            job = self.upload_job_with(connection, job_key)
            return UploadClaim(job=job, claimed=True, reason="reclaimed")

    def finish_upload_job(
        self,
        job_key: str,
        state: str,
        *,
        bvid: str = "",
        remote_path: str = "",
        message: str = "",
        fingerprint: str | None = None,
    ) -> UploadJob | None:
        now = int(time.time())
        with self.db.transaction() as connection:
            if fingerprint is None:
                connection.execute(
                    "UPDATE upload_jobs SET state = ?, bvid = ?, remote_path = ?,"
                    " message = ?, updated_at = ? WHERE job_key = ?",
                    (state, bvid, remote_path, message, now, job_key),
                )
            else:
                connection.execute(
                    "UPDATE upload_jobs SET state = ?, bvid = ?, remote_path = ?,"
                    " message = ?, fingerprint = ?, updated_at = ? WHERE job_key = ?",
                    (state, bvid, remote_path, message, fingerprint, now, job_key),
                )
            row = connection.execute(
                "SELECT * FROM upload_jobs WHERE job_key = ?", (job_key,)
            ).fetchone()
        return _row_to_job(row) if row is not None else None

    def clear_upload_job(self, job_key: str) -> None:
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM upload_jobs WHERE job_key = ?", (job_key,))

    @staticmethod
    def upload_job_with(connection: sqlite3.Connection, job_key: str) -> UploadJob:
        row = connection.execute(
            "SELECT * FROM upload_jobs WHERE job_key = ?", (job_key,)
        ).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise KeyError(job_key)
        return _row_to_job(row)

    # -------------------------------------------------------------- anchors

    def save_anchor(
        self,
        name: str,
        url: str,
        *,
        enabled: bool = True,
        config: dict[str, Any] | None = None,
    ) -> None:
        payload = json.dumps(config or {}, ensure_ascii=False)
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO anchors(name, url, enabled, config_json, updated_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(name) DO UPDATE SET url = excluded.url,"
                " enabled = excluded.enabled, config_json = excluded.config_json,"
                " updated_at = excluded.updated_at",
                (name, url, 1 if enabled else 0, payload, int(time.time())),
            )

    def all_anchors(self) -> list[dict[str, Any]]:
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM anchors ORDER BY name ASC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                config = json.loads(row["config_json"] or "{}")
            except ValueError:
                config = {}
            result.append(
                {
                    "name": str(row["name"]),
                    "url": str(row["url"]),
                    "enabled": bool(row["enabled"]),
                    "config": config,
                    "updated_at": int(row["updated_at"] or 0),
                }
            )
        return result

    def delete_anchor(self, name: str) -> None:
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM anchors WHERE name = ?", (name,))

    # ---------------------------------------------------------------- stats

    def upsert_stats(self, month: str, target_name: str, summary: dict[str, Any]) -> None:
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO stats(month, target_name, live_days, sessions, late_days,"
                " late_sessions, total_duration_seconds, on_time_rate, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(month, target_name) DO UPDATE SET"
                " live_days = excluded.live_days, sessions = excluded.sessions,"
                " late_days = excluded.late_days, late_sessions = excluded.late_sessions,"
                " total_duration_seconds = excluded.total_duration_seconds,"
                " on_time_rate = excluded.on_time_rate, updated_at = excluded.updated_at",
                (
                    month,
                    target_name,
                    int(summary.get("live_days", 0) or 0),
                    int(summary.get("sessions", 0) or 0),
                    int(summary.get("late_days", 0) or 0),
                    int(summary.get("late_sessions", 0) or 0),
                    int(summary.get("total_duration_seconds", 0) or 0),
                    float(summary.get("on_time_rate", 100.0) or 0.0),
                    int(time.time()),
                ),
            )

    def stats(self, month: str, target_name: str) -> dict[str, Any] | None:
        with self.db.read() as connection:
            row = connection.execute(
                "SELECT * FROM stats WHERE month = ? AND target_name = ?",
                (month, target_name),
            ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    # ------------------------------------------------------------ internals

    def _load_with(self, connection: sqlite3.Connection, session_id: str) -> SessionRecord:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return self._record_with(connection, row)

    def _record_with(self, connection: sqlite3.Connection, row: sqlite3.Row) -> SessionRecord:
        session_id = str(row["session_id"])
        part_rows = connection.execute(
            "SELECT * FROM parts WHERE session_id = ? ORDER BY part_index ASC",
            (session_id,),
        ).fetchall()
        file_rows = connection.execute(
            "SELECT * FROM session_files WHERE session_id = ? ORDER BY path ASC",
            (session_id,),
        ).fetchall()
        return SessionRecord(
            session_id=session_id,
            target_name=str(row["target_name"] or ""),
            target_url=str(row["target_url"] or ""),
            status=str(row["status"] or "STARTING"),
            created_epoch=int(row["created_epoch"] or 0),
            detected_start_epoch=row["detected_start_epoch"],
            detected_start_iso=row["detected_start_iso"],
            ended_epoch=row["ended_epoch"],
            room_title=str(row["room_title"] or ""),
            bvid=row["bvid"],
            title=str(row["title"] or ""),
            attempts=int(row["attempts"] or 0),
            error=str(row["error"] or ""),
            files=[
                MediaFile(
                    path=str(item["path"]),
                    size=int(item["size"] or 0),
                    duration_seconds=item["duration_seconds"],
                    sha256=item["sha256"],
                    source=item["source"],
                    uploaded=bool(item["uploaded"]),
                )
                for item in file_rows
            ],
            parts=[
                SessionPart(
                    index=int(item["part_index"]),
                    status=normalize_part_state(item["status"]),
                    title=str(item["title"] or ""),
                    path=str(item["path"] or ""),
                    source_path=str(item["source_path"] or ""),
                    danmaku_path=str(item["danmaku_path"] or ""),
                    size=int(item["size"] or 0),
                    duration_seconds=item["duration_seconds"],
                    bvid=item["bvid"],
                    uploaded_at=item["uploaded_at"],
                    error=str(item["error"] or ""),
                    cloud_status=str(item["cloud_status"] or ""),
                    cloud_error=str(item["cloud_error"] or ""),
                    cloud_path=str(item["cloud_path"] or ""),
                    cloud_uploaded_at=item["cloud_uploaded_at"],
                    cloud_attempts=int(item["cloud_attempts"] or 0),
                )
                for item in part_rows
            ],
            record_mode=str(row["record_mode"] or "record"),
            scheduled_start_epoch=row["scheduled_start_epoch"],
            late=bool(row["late"]),
            late_minutes=int(row["late_minutes"] or 0),
            last_seen_live_epoch=row["last_seen_live_epoch"],
            reconnect_count=int(row["reconnect_count"] or 0),
            reconnect_seconds=int(row["reconnect_seconds"] or 0),
            collection_id=str(row["collection_id"] or ""),
            collection_status=str(row["collection_status"] or ""),
            cloud_backup=bool(row["cloud_backup"]),
            cloud_provider=str(row["cloud_provider"] or ""),
            cloud_remote=str(row["cloud_remote"] or ""),
        )

    def _write_with(self, connection: sqlite3.Connection, session: SessionRecord) -> None:
        columns = ", ".join(_SESSION_COLUMNS)
        placeholders = ", ".join("?" for _ in _SESSION_COLUMNS)
        updates = ", ".join(
            f"{column} = excluded.{column}" for column in _SESSION_COLUMNS if column != "session_id"
        )
        now = int(time.time())
        connection.execute(
            f"INSERT INTO sessions({columns}, updated_at) VALUES({placeholders}, ?)"
            f" ON CONFLICT(session_id) DO UPDATE SET {updates}, updated_at = excluded.updated_at",
            (*_session_params(session), now),
        )
        part_columns = ", ".join(_PART_COLUMNS)
        part_placeholders = ", ".join("?" for _ in _PART_COLUMNS)
        part_updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in _PART_COLUMNS
            if column not in {"session_id", "part_index"}
        )
        keep_indexes: list[int] = []
        for part in session.parts:
            connection.execute(
                f"INSERT INTO parts({part_columns}, updated_at) VALUES({part_placeholders}, ?)"
                f" ON CONFLICT(session_id, part_index) DO UPDATE SET"
                f" {part_updates}, updated_at = excluded.updated_at",
                (*_part_params(session.session_id, part), now),
            )
            keep_indexes.append(int(part.index))
        if keep_indexes:
            index_placeholders = ",".join("?" for _ in keep_indexes)
            connection.execute(
                f"DELETE FROM parts WHERE session_id = ? AND part_index NOT IN ({index_placeholders})",
                (session.session_id, *keep_indexes),
            )
        else:
            connection.execute("DELETE FROM parts WHERE session_id = ?", (session.session_id,))
        connection.execute("DELETE FROM session_files WHERE session_id = ?", (session.session_id,))
        for item in session.files:
            connection.execute(
                "INSERT INTO session_files(session_id, path, size, duration_seconds, sha256,"
                " source, uploaded) VALUES(?,?,?,?,?,?,?)",
                _file_params(session.session_id, item),
            )

    def _write_snapshot(self, session: SessionRecord) -> None:
        """Persist ``session.json`` as a debug/export snapshot (best effort)."""

        try:
            path = self.state_path(session.session_id)
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
        except OSError:
            # The snapshot is not the source of truth; never fail a save on it.
            pass

    def _migrate_legacy_json(self) -> None:
        with self.db.read() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM sessions").fetchone()
        if row is not None and int(row["total"] or 0) > 0:
            return
        for path in sorted(self.root.glob("*/session.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    session = SessionRecord.from_dict(json.load(handle))
            except (OSError, ValueError, KeyError):
                continue
            try:
                self.save(session)
            except (sqlite3.Error, OSError):
                continue


@dataclass(slots=True)
class LockInfo:
    pid: int
    started_at: int = 0
    command: str = ""


def read_lock_info(path: Path) -> LockInfo | None:
    """Read the recorded lock holder without taking the lock."""

    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except ValueError:
            return None
        try:
            pid = int(payload.get("pid", 0))
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None
        return LockInfo(
            pid=pid,
            started_at=int(payload.get("started_at", 0) or 0),
            command=str(payload.get("command", "")),
        )
    try:
        pid = int(raw)
    except ValueError:
        return None
    if pid <= 0:
        return None
    return LockInfo(pid=pid)


def lock_is_held(path: Path) -> bool:
    """Probe the lock without disturbing the holder."""

    target = Path(path)
    if not target.exists():
        return False
    try:
        fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


class SingleInstanceLock:
    """flock-based single instance guard with an auditable holder record."""

    def __init__(self, path: Path, *, command: str = "") -> None:
        self.path = Path(path)
        self.command = command
        self.acquired = False
        self._fd = -1

    def __enter__(self) -> SingleInstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            holder = read_lock_info(self.path)
            os.close(self._fd)
            self._fd = -1
            detail = f" (pid {holder.pid})" if holder is not None else ""
            raise RuntimeError(
                f"Another recorder process is already running{detail}: {self.path}"
            ) from exc
        os.ftruncate(self._fd, 0)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "started_at": int(time.time()),
                "command": self.command,
            },
            ensure_ascii=False,
        )
        os.write(self._fd, payload.encode("utf-8"))
        os.fsync(self._fd)
        self.acquired = True
        return self

    def holder(self) -> LockInfo | None:
        return read_lock_info(self.path)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.acquired:
            return
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = -1
        self.acquired = False
        holder = read_lock_info(self.path)
        if holder is not None and holder.pid != os.getpid():
            # Someone else reclaimed the path after we released it.
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
