from pathlib import Path

from douyin_bili_recorder.upload_progress import UploadProgressSampler, UploadProgressStore


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


def test_progress_sampler_accepts_python_biliup_process_name() -> None:
    output = (
        "time,,interface,state,bytes_in,bytes_out,rx_dupe,rx_ooo,re-tx,rtt_avg,rcvsize,tx_win,tc_class,tc_mgt,cc_algo,P,C,R,W,\n"
        "23:12:24.620435,python3.14.66714,,,79618,17532589,0,0,0,,,,,,,,,,,\n"
    )
    sample = UploadProgressSampler.parse_nettop_sample(66714, output)
    assert sample is not None
    assert sample.bytes_out == 17532589
