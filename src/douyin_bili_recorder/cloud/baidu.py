from __future__ import annotations

import shutil
import threading
from pathlib import Path

from ..bandwidth import BANDWIDTH
from .driver import (
    CloudDriverError,
    DriverCapabilities,
    DriverContext,
    UploadOutcome,
    detect_provider,
)


def _resolve(binary: str) -> str | None:
    if not binary:
        return None
    candidate = shutil.which(binary)
    if candidate:
        return candidate
    path = Path(binary).expanduser()
    if path.is_file():
        return str(path)
    return None


class BaiduCliDriver:
    """Baidu Netdisk uploads through bypy / bypy-next with parallel threads."""

    name = "baidu-cli"
    capabilities = DriverCapabilities(
        chunked=True,
        concurrent_parts=4,
        direct_api=True,
        bandwidth_limit=False,
        notes="bypy-next --upload-threads 单文件分片并发",
    )

    def __init__(self, remote: str, context: DriverContext, binary: str) -> None:
        self.remote = remote
        self.context = context
        self.binary = binary
        self.capabilities = DriverCapabilities(
            chunked=True,
            concurrent_parts=max(1, int(context.config.cloud_max_concurrency)),
            direct_api=True,
            bandwidth_limit=False,
            notes=f"外部 CLI: {Path(binary).name}",
        )

    def _run(self, args: list[str], cancel_event: threading.Event):
        config = self.context.config
        try:
            return self.context.runner.run(
                args,
                cancel_event=cancel_event,
                timeout_seconds=config.cloud_upload_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise CloudDriverError(f"百度网盘 CLI 不存在或不可执行：{self.binary}") from exc

    def ensure_dir(self, remote_dir: str, cancel_event: threading.Event) -> None:
        result = self._run([self.binary, "mkdir", remote_dir], cancel_event)
        if result.cancelled:
            raise CloudDriverError("创建百度网盘目录已停止")
        if result.timed_out:
            raise CloudDriverError("创建百度网盘目录超时")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"创建百度网盘目录失败：{detail}")

    def upload(
        self,
        local_path: Path,
        remote_path: str,
        cancel_event: threading.Event,
    ) -> UploadOutcome:
        config = self.context.config
        remote_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else ""
        command = [
            self.binary,
            "upload",
            str(local_path),
            remote_dir,
            "--upload-threads",
            str(max(1, int(config.cloud_max_concurrency))),
        ]
        limit = BANDWIDTH.cloud_limit_kbps()
        if limit > 0:
            command.extend(["--rate-limit", f"{limit}k"])
        result = self._run(command, cancel_event)
        if result.cancelled:
            raise CloudDriverError("百度网盘上传已停止")
        if result.timed_out:
            raise CloudDriverError(f"百度网盘上传超时：{local_path.name}")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"百度网盘上传失败：{local_path.name}：{detail}")
        return UploadOutcome(remote_paths=[remote_path], messages=list(result.lines))

    def probe(self, remote: str) -> list[str]:
        result = self._run([self.binary, "list", remote], threading.Event())
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"百度网盘远端不可访问：{detail}")
        return list(result.lines)


def baidu_factory(remote: str, context: DriverContext) -> BaiduCliDriver | None:
    binary = _resolve(context.config.cloud_baidu_cli)
    if binary is None:
        return None
    if detect_provider(remote) != "baidu":
        return None
    return BaiduCliDriver(remote, context, binary)
