from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from douyin_bili_recorder import quark_official
from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.quark_official import QuarkOfficialClientError


def _config(tmp_path: Path, *, rclone_bin: str = "rclone"):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[app]
data_dir = "data"

[cloud]
rclone_bin = "{rclone_bin}"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def _backup_db(root: Path, task_path: Path) -> Path:
    db_path = root / "persistence" / "account" / "backup.db"
    db_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE backup_task (
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                status INTEGER NOT NULL,
                progress REAL,
                relativePath TEXT,
                link_dir_path TEXT,
                extraInfo TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO backup_task VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(task_path), task_path.name, 1, 100.0, "", "", "{}"),
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def test_find_quark_app_uses_known_bundle_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "QuarkCloudDrive.app"
    app.mkdir()
    monkeypatch.setattr(quark_official, "QUARK_APP_CANDIDATES", (app,))

    assert quark_official.find_quark_app() == app


def test_backup_tasks_reads_official_database_without_modifying_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    support = tmp_path / "QuarkCloudDrive"
    task_path = tmp_path / "DouyinBiliRecorder"
    task_path.mkdir()
    db_path = _backup_db(support, task_path)
    before = db_path.read_bytes()
    monkeypatch.setattr(quark_official, "QUARK_SUPPORT", support)

    tasks = quark_official.backup_tasks()

    assert tasks == [
        {
            "path": str(task_path),
            "name": "DouyinBiliRecorder",
            "status": 1,
            "progress": 100.0,
            "relative_path": "",
            "link_dir_path": "",
            "extra": "{}",
            "database": str(db_path),
        }
    ]
    assert db_path.read_bytes() == before


def test_official_channel_reports_missing_backup_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "QuarkCloudDrive.app"
    app.mkdir()
    sync_dir = tmp_path / "recordings"
    sync_dir.mkdir()
    monkeypatch.setattr(quark_official, "find_quark_app", lambda: app)
    monkeypatch.setattr(quark_official, "quark_version", lambda _app: "7.4.0.818")
    monkeypatch.setattr(quark_official, "backup_tasks", lambda: [])

    result = quark_official.test_official_channel(
        _config(tmp_path),
        str(sync_dir),
        "quark:/quark/DouyinBiliRecorder",
    )

    assert result["installed"] is True
    assert result["ok"] is False
    assert result["backup_task_count"] == 0
    assert "电脑备份" in result["message"]
    assert not (sync_dir / "__codex_vip_test__").exists()


def test_official_channel_probe_verifies_remote_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "QuarkCloudDrive.app"
    app.mkdir()
    sync_dir = tmp_path / "recordings"
    sync_dir.mkdir()
    rclone = tmp_path / "rclone"
    rclone.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    rclone.chmod(0o755)
    calls: list[list[str]] = []

    monkeypatch.setattr(quark_official, "find_quark_app", lambda: app)
    monkeypatch.setattr(quark_official, "quark_version", lambda _app: "7.4.0.818")
    monkeypatch.setattr(
        quark_official,
        "backup_tasks",
        lambda: [{"path": str(sync_dir), "name": "recordings"}],
    )
    monkeypatch.setattr(quark_official, "_remote_size", lambda _bin, _remote: 1024)

    def fake_run(command, **_kwargs):
        calls.append([str(item) for item in command])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(quark_official.subprocess, "run", fake_run)

    result = quark_official.test_official_channel(
        _config(tmp_path, rclone_bin=str(rclone)),
        str(sync_dir),
        "quark:/quark/DouyinBiliRecorder",
        probe_size=1024,
    )

    assert result["ok"] is True
    assert result["cleanup_ok"] is True
    assert result["matched_task"]["path"] == str(sync_dir)
    assert calls and calls[-1][1:3] == ["deletefile", result["remote_path"]]
    assert not (sync_dir / "__codex_vip_test__").exists()


def test_ensure_official_backup_directory_requires_matching_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "QuarkCloudDrive.app"
    app.mkdir()
    sync_dir = tmp_path / "recordings"
    sync_dir.mkdir()
    monkeypatch.setattr(quark_official, "find_quark_app", lambda: app)
    monkeypatch.setattr(quark_official, "quark_version", lambda _app: "7.4.0.818")
    monkeypatch.setattr(
        quark_official,
        "backup_tasks",
        lambda: [{"path": str(tmp_path / "another-folder"), "name": "other"}],
    )

    with pytest.raises(QuarkOfficialClientError, match="电脑备份"):
        quark_official.ensure_official_backup_directory(sync_dir)
