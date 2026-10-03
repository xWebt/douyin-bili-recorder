from __future__ import annotations

import threading
from pathlib import Path

from ..bandwidth import BANDWIDTH
from ..openlist_api import OpenListApiClient, OpenListApiError
from ..paths import safe_path_name
from .driver import CloudDriverError, DriverCapabilities, DriverContext, UploadOutcome


class OpenListDriver:
    """Uploads through the local OpenList instance.

    Uses the native ``/api/fs/put`` endpoint when the rclone remote points at a
    local OpenList, and falls back to ``rclone copyto`` otherwise.
    """

    name = "openlist"
    capabilities = DriverCapabilities(
        chunked=False,
        concurrent_parts=1,
        direct_api=True,
        bandwidth_limit=True,
        notes="OpenList 单连接上传；rclone 回退支持 --bwlimit",
    )

    def __init__(self, remote: str, context: DriverContext) -> None:
        self.remote = remote
        self.context = context
        self._client: OpenListApiClient | None = None

    # ------------------------------------------------------------------ helpers

    def _api_client(self) -> OpenListApiClient | None:
        if self._client is None:
            config = self.context.config
            self._client = OpenListApiClient.from_rclone_remote(
                self.remote,
                rclone_bin=config.cloud_rclone_bin,
                timeout_seconds=config.cloud_upload_timeout_seconds,
            )
            if self._client is None:
                self.context.logger.info(
                    "OpenList native API unavailable for %s, using rclone", self.remote
                )
        return self._client

    def _rclone(
        self,
        args: list[str],
        cancel_event: threading.Event,
        *,
        timeout_seconds: int | None = None,
    ):
        config = self.context.config
        command = [config.cloud_rclone_bin, *args]
        limit = BANDWIDTH.cloud_limit_kbps()
        if limit > 0:
            command.extend(["--bwlimit", f"{limit}k"])
        try:
            return self.context.runner.run(
                command,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds or config.cloud_upload_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise CloudDriverError(
                f"rclone 不存在或不可执行：{config.cloud_rclone_bin}"
            ) from exc

    def _rclone_short(self, args: list[str], cancel_event: threading.Event):
        return self._rclone(args, cancel_event, timeout_seconds=60)

    # -------------------------------------------------------------------- API

    def ensure_dir(self, remote_dir: str, cancel_event: threading.Event) -> None:
        wanted = remote_dir.rstrip("/")
        anchor = wanted.rsplit("/", 1)[-1]
        parent = wanted.rsplit("/", 1)[0] if "/" in wanted else self.remote
        listed = self._rclone_short(
            ["lsf", parent, "--max-depth", "1", "--dirs-only"], cancel_event
        )
        if listed.cancelled:
            raise CloudDriverError("检查网盘目录已停止")
        if listed.timed_out:
            raise CloudDriverError("检查网盘目录超时")
        entries = {line.strip().rstrip("/") for line in listed.lines if line.strip()}
        if listed.returncode == 0 and anchor in entries:
            return
        result = self._rclone_short(["mkdir", remote_dir], cancel_event)
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
        client = self._api_client()
        if client is not None:
            try:
                client.upload(local_path, remote_path, cancel_event)
            except OpenListApiError as exc:
                raise CloudDriverError(str(exc)) from exc
            return UploadOutcome(remote_paths=[remote_path])

        result = self._rclone(
            [
                "copyto",
                str(local_path),
                remote_path,
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
                "--transfers",
                "1",
                "--checkers",
                "1",
            ],
            cancel_event,
        )
        if result.cancelled:
            raise CloudDriverError("网盘备份已停止")
        if result.timed_out:
            raise CloudDriverError(f"网盘上传超时：{local_path.name}")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"网盘上传失败：{local_path.name}：{detail}")
        return UploadOutcome(remote_paths=[remote_path], messages=list(result.lines))

    def probe(self, remote: str) -> list[str]:
        result = self._rclone(["lsf", remote, "--max-depth", "1"], threading.Event())
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"网盘远端不可访问：{detail}")
        return list(result.lines)


def _factory(remote: str, context: DriverContext) -> OpenListDriver | None:
    return OpenListDriver(remote, context)


def anchor_path(target_name: str) -> str:
    return safe_path_name(target_name, "未命名主播")
