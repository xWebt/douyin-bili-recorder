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
