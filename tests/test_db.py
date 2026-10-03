from __future__ import annotations

import json
import threading
from pathlib import Path

from douyin_bili_recorder.models import SessionPart, SessionRecord
from douyin_bili_recorder.state import (
    SessionStore,
    upload_job_key,
)


def _session(session_id: str = "session", parts: int = 0) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        created_epoch=1_700_000_000,
        title="anchor P01",
        parts=[
            SessionPart(index=index, status="PENDING", title=f"P{index}", path=f"/tmp/p{index}.mp4")
            for index in range(1, parts + 1)
        ],
    )


def test_sqlite_database_is_created_and_holds_parts(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(root)
    store.save(_session(parts=3))

    assert (root / SessionStore.DB_FILENAME).is_file()
    assert store.db.schema_version() >= 1
    loaded = store.load("session")
    assert [part.index for part in loaded.parts] == [1, 2, 3]
    assert loaded.parts[1].title == "P2"
    # session.json stays as an export snapshot.
    snapshot = json.loads((root / "session" / "session.json").read_text(encoding="utf-8"))
    assert snapshot["session_id"] == "session"


def test_sqlite_store_survives_snapshot_removal(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    SessionStore(root).save(_session())
    (root / "session" / "session.json").unlink()

    loaded = SessionStore(root).load("session")
    assert loaded.session_id == "session"


def test_legacy_session_json_is_imported_once(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    legacy_dir = root / "20260101-000000-anchor"
    legacy_dir.mkdir(parents=True)
    payload = SessionRecord(
        session_id="20260101-000000-anchor",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        created_epoch=42,
        title="legacy",
        parts=[SessionPart(index=1, status="UPLOAD_FAILED", title="legacy P01")],
    )
    (legacy_dir / "session.json").write_text(
        json.dumps(payload.to_dict(), ensure_ascii=False), encoding="utf-8"
    )

    store = SessionStore(root)
    imported = store.load("20260101-000000-anchor")
    assert imported.title == "legacy"
    assert imported.parts[0].status == "FAILED"


def test_delete_removes_rows_and_directory(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(root)
    store.save(_session())
    store.delete("session")

    assert store.all() == []
    assert not (root / "session").exists()


def test_update_part_is_transactional_across_threads(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(root)
    store.save(_session(parts=2))
    barrier = threading.Barrier(2)

    def worker(index: int) -> None:
        barrier.wait(timeout=5)
        store.update_part("session", index, lambda part: setattr(part, "status", "UPLOADED"))

    threads = [threading.Thread(target=worker, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    loaded = store.load("session")
    assert [part.status for part in loaded.parts] == ["UPLOADED", "UPLOADED"]
    assert [part.index for part in loaded.parts] == [1, 2]


def test_set_part_state_enforces_state_machine(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(root)
    session = _session(parts=1)
    session.parts[0].status = "DELETED"
    store.save(session)

    try:
        store.set_part_state("session", 1, "UPLOADING")
    except Exception as exc:  # noqa: BLE001
        assert "illegal part state transition" in str(exc)
    else:  # pragma: no cover - the transition must be rejected
        raise AssertionError("illegal transition was accepted")

    store.set_part_state("session", 1, "UPLOADING", force=True)
    assert store.load("session").parts[0].status == "UPLOADING"


def test_upload_job_claim_is_exclusive_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(root)
    store.save(_session(parts=1))
    key = upload_job_key("bilibili", "session", 1)

    first = store.claim_upload_job("bilibili", "session", 1, fingerprint="a")
    assert first.claimed is True

    second = store.claim_upload_job("bilibili", "session", 1, fingerprint="a")
    assert second.claimed is False
    assert second.job.succeeded is False
    assert second.reason == "already-running"

    store.finish_upload_job(key, "SUCCEEDED", bvid="BV0000000001", message="ok")
    third = store.claim_upload_job("bilibili", "session", 1, fingerprint="a")
    assert third.claimed is False
    assert third.job.succeeded is True
    assert third.reason == "already-succeeded"
    assert store.upload_job(key).bvid == "BV0000000001"

    store.finish_upload_job(key, "FAILED", message="boom")
    fourth = store.claim_upload_job("bilibili", "session", 1, fingerprint="b")
    assert fourth.claimed is True
    assert fourth.job.attempts == 2

    stale = store.claim_upload_job("bilibili", "session", 1, stale_seconds=0)
    assert stale.claimed is True


def test_anchor_and_stats_tables_are_usable(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = SessionStore(root)
    store.save_anchor("anchor", "https://live.douyin.com/1", config={"watch_mode": "all_day"})
    anchors = store.all_anchors()
    assert anchors[0]["name"] == "anchor"
    assert anchors[0]["config"]["watch_mode"] == "all_day"

    store.upsert_stats("2026-10", "anchor", {"live_days": 3, "sessions": 4, "on_time_rate": 75.0})
    row = store.stats("2026-10", "anchor")
    assert row is not None
    assert row["live_days"] == 3
    store.delete_anchor("anchor")
    assert store.all_anchors() == []
