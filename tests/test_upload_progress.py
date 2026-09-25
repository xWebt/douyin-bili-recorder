from pathlib import Path

from douyin_bili_recorder.upload_progress import UploadProgressStore


def test_upload_progress_store_round_trip(tmp_path: Path) -> None:
    store = UploadProgressStore(tmp_path)
    payload = {
        "available": True,
        "title": "anchor P01",
        "uploaded_bytes": 100,
        "total_bytes": 200,
        "percent": 50,
    }
    store.save(payload)
    assert store.load() == payload
    store.clear()
    assert store.load() == {}


def test_upload_progress_store_tracks_multiple_uploads(tmp_path: Path) -> None:
    store = UploadProgressStore(tmp_path)
    store.upsert(
        "session-a:1",
        {"available": True, "target": "A", "percent": 10, "updated_at": "2026-09-25T01:00:00"},
    )
    store.upsert(
        "session-b:1",
        {"available": True, "target": "B", "percent": 20, "updated_at": "2026-09-25T01:00:01"},
    )

    uploads = store.load_all()
    assert [item["target"] for item in uploads] == ["B", "A"]
    assert store.load()["target"] == "B"
    store.remove("session-b:1")
    assert [item["target"] for item in store.load_all()] == ["A"]
