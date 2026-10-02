from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.openlist import OpenListManager


def test_openlist_manager_starts_configured_binary(tmp_path: Path, monkeypatch) -> None:
    binary = tmp_path / "tools" / "openlist" / "openlist"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    calls = []

    class FakeProcess:
        pid = 1234

        @staticmethod
        def poll() -> None:
            return None

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("douyin_bili_recorder.openlist.subprocess.Popen", fake_popen)
    manager = OpenListManager(tmp_path, logging.getLogger("test"))
    ready = iter([False, True])
    monkeypatch.setattr(manager, "is_ready", lambda timeout=0.3: next(ready))

    assert manager.ensure_running(timeout_seconds=1) is True
    assert calls[0][0] == [str(binary), "--data", str(tmp_path / "openlist-data"), "server"]
    assert manager.owner_pid_path.exists()


def test_openlist_stop_reclaims_owned_listener_without_pid_file(tmp_path: Path, monkeypatch) -> None:
    manager = OpenListManager(tmp_path, logging.getLogger("test"))
    stopped: list[int] = []
    monkeypatch.setattr(manager, "is_ready", lambda timeout=0.3: True)
    monkeypatch.setattr(manager, "_owned_listener_pid", lambda: 4321)
    monkeypatch.setattr(manager, "_stop_process", lambda pid: stopped.append(pid))

    manager.stop()

    assert stopped == [4321]


def test_openlist_reuses_existing_listener(tmp_path: Path, monkeypatch) -> None:
    manager = OpenListManager(tmp_path, logging.getLogger("test"))
    stopped: list[int] = []
    monkeypatch.setattr(manager, "is_ready", lambda timeout=0.3: True)
    monkeypatch.setattr(manager, "_stop_process", lambda pid: stopped.append(pid))

    assert manager.ensure_running(timeout_seconds=1) is True
    assert stopped == []
