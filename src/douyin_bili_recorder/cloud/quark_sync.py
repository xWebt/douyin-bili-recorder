from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

from ..quark_official import (
    QuarkOfficialClientError,
    ensure_official_backup_directory,
)

from .driver import (
    CloudDriverError,
    DriverCapabilities,
    DriverContext,
    UploadOutcome,
    detect_provider,
)


class QuarkSyncFolderDriver:
    """Uploads through the official Quark client's computer-backup folder.

    The recorder never talks to Quark's upload API in this mode. It atomically
    copies the finished MP4 into the folder watched by the official client,
    then verifies through rclone/OpenList that the remote file reached the
    expected size. This keeps OpenList out of the upload path while still
    giving the recorder a completion signal.
    """

    name = "quark-sync-vip"
    capabilities = DriverCapabilities(
        chunked=False,
        concurrent_parts=1,
        direct_api=False,
        bandwidth_limit=False,
        notes="夸克官方客户端电脑备份（真 VIP 通道）",
    )

    def __init__(self, remote: str, context: DriverContext) -> None:
        self.remote = remote
        self.context = context
        self.sync_dir = Path(context.config.cloud_quark_sync_dir).expanduser()
        self.remote_root = context.config.cloud_quark_sync_remote_root.rstrip("/")
        self.timeout_seconds = context.config.cloud_quark_sync_timeout_seconds
        if not self.sync_dir or not self.remote_root:
            raise CloudDriverError("夸克电脑备份目录未配置")
        try:
            ensure_official_backup_directory(self.sync_dir)
        except QuarkOfficialClientError as exc:
            raise CloudDriverError(str(exc)) from exc

    def _relative_remote(self, remote_path: str) -> str:
        path = remote_path.rstrip("/")
        if path == self.remote_root:
            return ""
        prefix = f"{self.remote_root}/"
        if not path.startswith(prefix):
            raise CloudDriverError(
                f"远端路径不在 quark_sync_remote_root 下：{remote_path}"
            )
        return path[len(prefix):]

    def _local_path(self, remote_path: str) -> Path:
        relative = self._relative_remote(remote_path)
        target = self.sync_dir / relative
        resolved_dir = self.sync_dir.resolve()
        resolved_target = target.resolve()
        if resolved_target != resolved_dir and resolved_dir not in resolved_target.parents:
            raise CloudDriverError("同步目录路径越界")
        return target

    def ensure_dir(self, remote_dir: str, cancel_event: threading.Event) -> None:
        target = self._local_path(remote_dir)
        target.mkdir(parents=True, exist_ok=True)

    def upload(
        self,
        local_path: Path,
        remote_path: str,
        cancel_event: threading.Event,
    ) -> UploadOutcome:
        target = self._local_path(remote_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.codex-part")
        try:
            shutil.copy2(local_path, temp)
            with temp.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, target)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise CloudDriverError(f"复制到夸克官方同步目录失败：{exc}") from exc

        self.context.logger.info(
            "waiting for official Quark client to upload %s", remote_path
        )
        deadline = time.monotonic() + self.timeout_seconds
        expected = local_path.stat().st_size
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise CloudDriverError("夸克官方客户端上传已停止")
            remote_size = self._remote_size(remote_path)
            if remote_size is not None and remote_size >= expected:
                return UploadOutcome(
                    remote_paths=[remote_path],
                    messages=["uploaded through official Quark sync client"],
                )
            time.sleep(10)
        raise CloudDriverError(
            "夸克官方客户端在超时前未完成同步；请确认客户端已登录、同步目录正确且保持运行"
        )

    def _remote_size(self, remote_path: str) -> int | None:
        command = [
            self.context.config.cloud_rclone_bin,
            "size",
            remote_path,
            "--json",
        ]
        try:
            result = self.context.runner.run(command, timeout_seconds=30)
        except FileNotFoundError as exc:
            raise CloudDriverError("rclone 不存在，无法校验官方客户端上传结果") from exc
        if result.returncode != 0:
            return None
        text = "\n".join(result.lines).strip()
        if not text:
            return None
        try:
            payload = json.loads(text.splitlines()[-1])
            return int(payload.get("bytes", 0))
        except (ValueError, TypeError):
            return None

    def probe(self, remote: str) -> list[str]:
        result = self.context.runner.run(
            [self.context.config.cloud_rclone_bin, "lsf", remote, "--max-depth", "1"],
            timeout_seconds=60,
        )
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"夸克远端不可访问：{detail}")
        return list(result.lines)


def quark_sync_factory(remote: str, context: DriverContext) -> QuarkSyncFolderDriver | None:
    if detect_provider(remote) != "quark":
        return None
    if not context.config.cloud_quark_sync_dir.strip():
        return None
    if not context.config.cloud_quark_sync_remote_root.strip():
        return None
    return QuarkSyncFolderDriver(remote, context)
