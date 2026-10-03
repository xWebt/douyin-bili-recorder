from __future__ import annotations

import threading
from pathlib import Path

from ..bandwidth import BANDWIDTH
from .driver import CloudDriverError, DriverCapabilities, DriverContext, UploadOutcome


class RcloneDriver:
    """Generic rclone driver with multi-thread streams and bandwidth limiting."""

    name = "rclone"
    capabilities = DriverCapabilities(
        chunked=True,
        concurrent_parts=4,
        direct_api=False,
        bandwidth_limit=True,
        notes="rclone copyto --multi-thread-streams + --bwlimit",
    )

    def __init__(self, remote: str, context: DriverContext) -> None:
        self.remote = remote
        self.context = context

    def _run(self, args: list[str], cancel_event: threading.Event):
        config = self.context.config
        try:
            return self.context.runner.run(
                args,
                cancel_event=cancel_event,
                timeout_seconds=config.cloud_upload_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise CloudDriverError(
                f"rclone 不存在或不可执行：{config.cloud_rclone_bin}"
            ) from exc

    def ensure_dir(self, remote_dir: str, cancel_event: threading.Event) -> None:
        result = self._run(
            [self.context.config.cloud_rclone_bin, "mkdir", remote_dir], cancel_event
        )
        if result.cancelled:
            raise CloudDriverError("创建网盘目录已停止")
        if result.timed_out:
            raise CloudDriverError("创建网盘目录超时")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"创建网盘目录失败：{detail}")

    def upload(
        self,
        local_path: Path,
        remote_path: str,
        cancel_event: threading.Event,
    ) -> UploadOutcome:
        config = self.context.config
        streams = max(1, int(config.cloud_max_concurrency))
        command = [
            config.cloud_rclone_bin,
            "copyto",
            str(local_path),
            remote_path,
            "--multi-thread-streams",
            str(streams),
            "--transfers",
            "1",
            "--checkers",
            "1",
            "--stats",
            "1s",
            "--stats-one-line",
            "--retries",
            "3",
            "--low-level-retries",
            "5",
            "--retries-sleep",
            "15s",
            "--timeout",
            "60m",
            "--contimeout",
            "1m",
        ]
        limit = BANDWIDTH.cloud_limit_kbps()
        if limit > 0:
            command.extend(["--bwlimit", f"{limit}k"])
        result = self._run(command, cancel_event)
        if result.cancelled:
            raise CloudDriverError("网盘备份已停止")
        if result.timed_out:
            raise CloudDriverError(f"网盘上传超时：{local_path.name}")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"网盘上传失败：{local_path.name}：{detail}")
        return UploadOutcome(remote_paths=[remote_path], messages=list(result.lines))

    def probe(self, remote: str) -> list[str]:
        result = self._run(
            [self.context.config.cloud_rclone_bin, "lsf", remote, "--max-depth", "1"],
            threading.Event(),
        )
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"网盘远端不可访问：{detail}")
        return list(result.lines)


def rclone_factory(remote: str, context: DriverContext) -> RcloneDriver | None:
    return RcloneDriver(remote, context)
