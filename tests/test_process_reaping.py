from __future__ import annotations

import os
from pathlib import Path

from douyin_bili_recorder import process as process_module
from douyin_bili_recorder.process import ChildProcessRegistry, terminate_all_children
from douyin_bili_recorder.state import (
    SingleInstanceLock,
    lock_is_held,
    read_lock_info,
)


class FakeProcess:
    def __init__(self, pid: int, alive: bool = True) -> None:
        self.pid = pid
        self.returncode = None if alive else 0

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0


def test_registry_terminates_live_children_and_skips_finished(monkeypatch) -> None:
    registry = ChildProcessRegistry()
    live = FakeProcess(101)
    done = FakeProcess(202, alive=False)
    registry.register(live)
    registry.register(done)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_group",
        lambda pid, **kwargs: terminated.append(pid) or True,
    )

    result = registry.terminate_all()

    assert result == [101]
    assert terminated == [101]
    assert registry.active() == []


def test_registry_keeps_protected_children(monkeypatch) -> None:
    registry = ChildProcessRegistry()
    keep = FakeProcess(303)
    other = FakeProcess(404)
    registry.register(keep)
    registry.register(other)
    monkeypatch.setattr(
        process_module, "terminate_process_group", lambda pid, **kwargs: True
    )

    terminated = registry.terminate_all(keep=[keep])

    assert terminated == [404]
    assert [item.pid for item in registry.active()] == [303]


def test_terminate_all_children_uses_shared_registry(monkeypatch) -> None:
    shared = process_module.SHARED_CHILD_PROCESSES
    child = FakeProcess(505)
    shared.register(child)
    monkeypatch.setattr(
        process_module, "terminate_process_group", lambda pid, **kwargs: True
    )

    assert terminate_all_children() == [505]
    assert shared.active() == []


def test_single_instance_lock_records_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / "recorder.lock"

    with SingleInstanceLock(lock_path, command="recorder worker") as lock:
        info = lock.holder()
        assert info is not None
        assert info.pid == os.getpid()
        assert info.command == "recorder worker"
        assert read_lock_info(lock_path).pid == os.getpid()  # type: ignore[union-attr]
        assert lock_is_held(lock_path) is True

    assert not lock_path.exists()
    assert lock_is_held(lock_path) is False


def test_read_lock_info_accepts_legacy_pid_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "recorder.lock"
    lock_path.write_text("4242", encoding="utf-8")

    info = read_lock_info(lock_path)

    assert info is not None
    assert info.pid == 4242
    assert info.command == ""


def test_single_instance_lock_refuses_live_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / "recorder.lock"
    with SingleInstanceLock(lock_path):
        try:
            with SingleInstanceLock(lock_path):
                pass
        except RuntimeError as exc:
            assert "already running" in str(exc)
        else:  # pragma: no cover - the second acquire must fail
            raise AssertionError("second lock acquisition unexpectedly succeeded")


def test_release_keeps_foreign_lock_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "recorder.lock"
    with SingleInstanceLock(lock_path):
        # Simulate another process reclaiming the file content after release.
        lock_path.write_text('{"pid": 999999, "command": "other"}', encoding="utf-8")

    assert lock_path.exists()
    assert read_lock_info(lock_path).pid == 999999  # type: ignore[union-attr]
