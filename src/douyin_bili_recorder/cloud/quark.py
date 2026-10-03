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


class QuarkCliDriver:
    """Chunked, multi-connection Quark uploads through an external CLI.

    The CLI (for example ``quarkpan`` or ``kuake-pipe``) owns the private-API
    details; this driver only standardises the invocation so the rest of the
    recorder never has to care which implementation is installed.
    """

    name = "quark-cli"
    capabilities = DriverCapabilities(
        chunked=True,
        concurrent_parts=4,
        direct_api=True,
        bandwidth_limit=False,
        notes="通过外部 Quark CLI 分片并发上传",
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

    def _base_command(self) -> list[str]:
        config = self.context.config
        command = [self.binary]
        cookie = str(config.cloud_quark_cookie_file or "").strip()
        if cookie:
            command.extend(["--cookie-file", cookie])
        return command

    def _run(self, args: list[str], cancel_event: threading.Event):
        config = self.context.config
        try:
            return self.context.runner.run(
                args,
                cancel_event=cancel_event,
                timeout_seconds=config.cloud_upload_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise CloudDriverError(f"夸克 CLI 不存在或不可执行：{self.binary}") from exc

    def ensure_dir(self, remote_dir: str, cancel_event: threading.Event) -> None:
        result = self._run([*self._base_command(), "mkdir", "-p", remote_dir], cancel_event)
        if result.cancelled:
            raise CloudDriverError("创建夸克目录已停止")
        if result.timed_out:
            raise CloudDriverError("创建夸克目录超时")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"创建夸克目录失败：{detail}")

    def upload(
        self,
        local_path: Path,
        remote_path: str,
        cancel_event: threading.Event,
    ) -> UploadOutcome:
        config = self.context.config
        limit = BANDWIDTH.cloud_limit_kbps()
        command = [
            *self._base_command(),
            "upload",
            "--chunk-size",
            f"{max(1, int(config.cloud_chunk_size_mb))}M",
            "--concurrency",
            str(max(1, int(config.cloud_max_concurrency))),
        ]
        if limit > 0:
            command.extend(["--rate-limit", f"{limit}k"])
        command.extend([str(local_path), remote_path])
        result = self._run(command, cancel_event)
        if result.cancelled:
            raise CloudDriverError("夸克上传已停止")
        if result.timed_out:
            raise CloudDriverError(f"夸克上传超时：{local_path.name}")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"夸克上传失败：{local_path.name}：{detail}")
        return UploadOutcome(remote_paths=[remote_path], messages=list(result.lines))

    def probe(self, remote: str) -> list[str]:
        result = self._run([*self._base_command(), "ls", remote], threading.Event())
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudDriverError(f"夸克远端不可访问：{detail}")
        return list(result.lines)


def quark_factory(remote: str, context: DriverContext) -> QuarkCliDriver | None:
    binary = _resolve(context.config.cloud_quark_cli)
    if binary is None:
        return None
    if detect_provider(remote) != "quark":
        return None
    return QuarkCliDriver(remote, context, binary)
