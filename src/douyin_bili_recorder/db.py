from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS anchors (
        name TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        config_json TEXT NOT NULL DEFAULT '{}',
        updated_at INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        target_name TEXT NOT NULL DEFAULT '',
        target_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'STARTING',
        created_epoch INTEGER NOT NULL DEFAULT 0,
        detected_start_epoch INTEGER,
        detected_start_iso TEXT,
        ended_epoch INTEGER,
        room_title TEXT NOT NULL DEFAULT '',
        bvid TEXT,
        title TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        record_mode TEXT NOT NULL DEFAULT 'record',
        scheduled_start_epoch INTEGER,
        late INTEGER NOT NULL DEFAULT 0,
        late_minutes INTEGER NOT NULL DEFAULT 0,
        last_seen_live_epoch INTEGER,
        reconnect_count INTEGER NOT NULL DEFAULT 0,
        reconnect_seconds INTEGER NOT NULL DEFAULT 0,
        collection_id TEXT NOT NULL DEFAULT '',
        collection_status TEXT NOT NULL DEFAULT '',
        cloud_backup INTEGER NOT NULL DEFAULT 0,
        cloud_provider TEXT NOT NULL DEFAULT '',
        cloud_remote TEXT NOT NULL DEFAULT '',
        updated_at INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_files (
        session_id TEXT NOT NULL,
        path TEXT NOT NULL,
        size INTEGER NOT NULL DEFAULT 0,
        duration_seconds REAL,
        sha256 TEXT,
        source TEXT,
        uploaded INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (session_id, path),
        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS parts (
        session_id TEXT NOT NULL,
        part_index INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        title TEXT NOT NULL DEFAULT '',
        path TEXT NOT NULL DEFAULT '',
        source_path TEXT NOT NULL DEFAULT '',
        danmaku_path TEXT NOT NULL DEFAULT '',
        size INTEGER NOT NULL DEFAULT 0,
        duration_seconds REAL,
        bvid TEXT,
        uploaded_at INTEGER,
        error TEXT NOT NULL DEFAULT '',
        cloud_status TEXT NOT NULL DEFAULT '',
        cloud_error TEXT NOT NULL DEFAULT '',
        cloud_path TEXT NOT NULL DEFAULT '',
        cloud_uploaded_at INTEGER,
        cloud_attempts INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (session_id, part_index),
        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS upload_jobs (
        job_key TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        part_index INTEGER NOT NULL,
        kind TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'RUNNING',
        attempts INTEGER NOT NULL DEFAULT 0,
        fingerprint TEXT NOT NULL DEFAULT '',
        bvid TEXT NOT NULL DEFAULT '',
        remote_path TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stats (
        month TEXT NOT NULL,
        target_name TEXT NOT NULL,
        live_days INTEGER NOT NULL DEFAULT 0,
        sessions INTEGER NOT NULL DEFAULT 0,
        late_days INTEGER NOT NULL DEFAULT 0,
        late_sessions INTEGER NOT NULL DEFAULT 0,
        total_duration_seconds INTEGER NOT NULL DEFAULT 0,
        on_time_rate REAL NOT NULL DEFAULT 100.0,
        updated_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (month, target_name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_target ON sessions(target_name, created_epoch)",
    "CREATE INDEX IF NOT EXISTS idx_parts_status ON parts(status)",
    "CREATE INDEX IF NOT EXISTS idx_upload_jobs_kind ON upload_jobs(kind, session_id, part_index)",
    "CREATE INDEX IF NOT EXISTS idx_upload_jobs_state ON upload_jobs(state, updated_at)",
)


class Database:
    """Thin SQLite helper with per-call connections.

    Connections are cheap, which keeps the store usable from the UI process,
    the recorder worker and every thread pool without sharing a handle.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
            self._initialized = True

    def schema_version(self) -> int:
        with self.read() as connection:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        if row is None:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0
