from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.state import SingleInstanceLock


def test_single_instance_lock_removes_stale_pid(tmp_path: Path) -> None:
    lock_path = tmp_path / "recorder.lock"
    lock_path.write_text("999999999", encoding="utf-8")

    with SingleInstanceLock(lock_path):
        assert lock_path.exists()

    assert not lock_path.exists()
