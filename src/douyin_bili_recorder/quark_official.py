from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import AppConfig


QUARK_APP_CANDIDATES = (
    Path("/Applications/QuarkCloudDrive.app"),
    Path.home() / "Applications/QuarkCloudDrive.app",
)
QUARK_SUPPORT = Path.home() / "Library" / "Application Support" / "QuarkCloudDrive"


class QuarkOfficialClientError(RuntimeError):
    """Raised when the official client cannot provide a verified backup path."""


def find_quark_app() -> Path | None:
    for candidate in QUARK_APP_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


def quark_version(app: Path | None) -> str:
    if app is None:
        return ""
    plist = app / "Contents" / "Info.plist"
    try:
        completed = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleShortVersionString", str(plist)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def backup_tasks() -> list[dict[str, Any]]:
    """Read the official client's backup task list without modifying it."""

    results: list[dict[str, Any]] = []
    for db_path in sorted(QUARK_SUPPORT.glob("persistence/*/backup.db")):
        try:
            uri = f"file:{db_path}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(
                    "SELECT path, name, status, progress, relativePath, link_dir_path, extraInfo "
                    "FROM backup_task"
                ).fetchall()
            finally:
                connection.close()
        except (sqlite3.Error, OSError):
            continue
        for row in rows:
            results.append(
                {
                    "path": str(row["path"] or ""),
                    "name": str(row["name"] or ""),
                    "status": row["status"],
                    "progress": row["progress"],
                    "relative_path": str(row["relativePath"] or ""),
                    "link_dir_path": str(row["link_dir_path"] or ""),
                    "extra": str(row["extraInfo"] or ""),
                    "database": str(db_path),
                }
            )
    return results


def _covers(task_path: str, target: Path) -> bool:
    if not task_path.strip():
        return False
    try:
        task = Path(os.path.expanduser(task_path)).resolve()
        target = target.resolve()
    except OSError:
        return False
    return task == target or task in target.parents


def ensure_official_backup_directory(sync_dir: str | Path) -> dict[str, Any]:
    """Return the official Quark backup task covering ``sync_dir``."""

    app = find_quark_app()
    if app is None:
        raise QuarkOfficialClientError(
            "未检测到夸克官方客户端，请先安装 QuarkCloudDrive.app。"
        )
    if not str(sync_dir).strip():
        raise QuarkOfficialClientError("请填写夸克客户端已开启“电脑备份”的本地目录。")
    sync_path = Path(os.path.expanduser(str(sync_dir))).resolve()
    if not sync_path.is_dir():
        raise QuarkOfficialClientError("夸克电脑备份目录不存在。")
    tasks = backup_tasks()
    matched = next(
        (task for task in tasks if _covers(str(task.get("path", "")), sync_path)),
        None,
    )
    if matched is None:
        raise QuarkOfficialClientError(
            "夸克客户端已安装，但没有找到覆盖该目录的“电脑备份”任务。"
            "请先在夸克客户端把该目录加入电脑备份，再回到这里测试。"
        )
    return {
        "app_path": str(app),
        "version": quark_version(app),
        "task": matched,
        "task_count": len(tasks),
    }


def open_official_client() -> dict[str, Any]:
    app = find_quark_app()
    if app is None:
        raise QuarkOfficialClientError(
            "未检测到夸克官方客户端，请先安装 QuarkCloudDrive.app。"
        )
    try:
        completed = subprocess.run(
            ["open", "-a", str(app)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QuarkOfficialClientError(f"打开夸克客户端失败：{exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise QuarkOfficialClientError(
            f"打开夸克客户端失败：{detail or completed.returncode}"
        )
    return {
        "ok": True,
        "message": "已打开夸克客户端，请进入“电脑备份”添加录制目录。",
    }


def _rclone_available(rclone_bin: str) -> bool:
    candidate = Path(os.path.expanduser(rclone_bin))
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return True
    return bool(shutil.which(rclone_bin))


def _remote_size(rclone_bin: str, remote_path: str) -> int | None:
    try:
        completed = subprocess.run(
            [rclone_bin, "size", remote_path, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        return int(payload.get("bytes", 0))
    except (ValueError, TypeError, IndexError):
        return None


def test_official_channel(
    config: AppConfig,
    sync_dir: str,
    remote_root: str,
    *,
    timeout_seconds: int = 90,
    probe_size: int = 256 * 1024,
) -> dict[str, Any]:
    """Verify the official Quark client path end to end.

    The client must have a "电脑备份" task covering ``sync_dir``. The probe is
    copied into that folder; the official client uploads it; rclone verifies the
    remote size. No OpenList write is performed.
    """

    app = find_quark_app()
    tasks = backup_tasks()
    result: dict[str, Any] = {
        "ok": False,
        "installed": app is not None,
        "app_path": str(app or ""),
        "version": quark_version(app),
        "sync_dir": sync_dir,
        "remote_root": remote_root,
        "backup_tasks": tasks,
        "backup_task_count": len(tasks),
        "matched_task": None,
        "cleanup_ok": None,
        "message": "",
    }
    if app is None:
        result["message"] = "未检测到夸克官方客户端，请先安装 QuarkCloudDrive.app。"
        return result
    sync_path = Path(os.path.expanduser(sync_dir.strip())).resolve() if sync_dir.strip() else None
    if sync_path is None or not sync_path.is_dir():
        result["message"] = "请填写夸克官方客户端中已开启“电脑备份”的本地目录。"
        return result
    matched = next((task for task in tasks if _covers(task.get("path", ""), sync_path)), None)
    if matched is None:
        result["message"] = (
            "夸克客户端已安装，但没有找到覆盖该目录的“电脑备份”任务。"
            "请先在夸克客户端把该目录加入电脑备份，再回到这里测试。"
        )
        return result
    result["matched_task"] = matched
    if not remote_root.strip():
        result["message"] = "请填写用于校验的同步远程根路径，例如 quark:/quark/DouyinBiliRecorder。"
        return result
    if not _rclone_available(config.cloud_rclone_bin):
        result["message"] = (
            "rclone 不可用，无法确认官方客户端是否完成上传。"
            "请先在应用设置中填写可执行的 rclone 路径。"
        )
        return result

    stamp = time.strftime("%Y%m%d-%H%M%S")
    probe_dir = sync_path / "__codex_vip_test__"
    probe_dir.mkdir(parents=True, exist_ok=True)
    local_probe = probe_dir / f"quark-vip-probe-{stamp}-{secrets.token_hex(4)}.bin"
    remote_probe = f"{remote_root.rstrip('/')}/__codex_vip_test__/{local_probe.name}"
    probe_size = max(1, min(int(probe_size), 16 * 1024 * 1024))
    started = time.monotonic()
    try:
        with local_probe.open("wb") as handle:
            handle.write(os.urandom(probe_size))
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + max(30, timeout_seconds)
        while time.monotonic() < deadline:
            size = _remote_size(config.cloud_rclone_bin, remote_probe)
            if size is not None and size >= probe_size:
                result.update(
                    ok=True,
                    message=(
                        f"官方客户端通道验证成功：{probe_size // 1024} KiB 已同步到远端"
                        f"（{time.monotonic() - started:.1f} 秒）。"
                    ),
                    remote_path=remote_probe,
                    elapsed_seconds=round(time.monotonic() - started, 1),
                )
                break
            time.sleep(3)
        if not result["ok"]:
            result.update(
                message=(
                    "探测文件已写入备份目录，但官方客户端未在超时前完成同步。"
                    "请确认夸克客户端已登录、备份任务已开启，且备份目录与填写路径完全一致。"
                ),
                remote_path=remote_probe,
                elapsed_seconds=round(time.monotonic() - started, 1),
            )
    finally:
        if result.get("ok"):
            try:
                cleanup = subprocess.run(
                    [config.cloud_rclone_bin, "deletefile", remote_probe],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                result["cleanup_ok"] = cleanup.returncode == 0
                if cleanup.returncode != 0:
                    detail = (cleanup.stderr or cleanup.stdout).strip()
                    result["cleanup_message"] = detail or "远端探测文件清理失败"
            except (OSError, subprocess.SubprocessError) as exc:
                result["cleanup_ok"] = False
                result["cleanup_message"] = str(exc)
        local_probe.unlink(missing_ok=True)
        try:
            probe_dir.rmdir()
        except OSError:
            pass
    return result
