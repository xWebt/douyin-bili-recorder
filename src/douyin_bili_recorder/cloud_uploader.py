from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import AppConfig, TargetConfig
from .models import SessionPart, SessionRecord
from .openlist_api import OpenListApiClient, OpenListApiError
from .paths import safe_path_name
from .process import ProcessRunner


@dataclass(slots=True)
class CloudUploadResult:
    uploaded: bool
    remote_paths: list[str]
    messages: list[str]


class CloudUploadError(RuntimeError):
    pass


class RcloneCloudUploader:
    def __init__(self, config: AppConfig, runner: ProcessRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger
        self._cancel_lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._part_locks: dict[str, threading.Lock] = {}
        self._part_locks_guard = threading.Lock()
        self._api_clients: dict[str, OpenListApiClient | None] = {}

    def upload_part(
        self,
        target: TargetConfig,
        session: SessionRecord,
        part: SessionPart,
    ) -> CloudUploadResult:
        key = f"{session.session_id}:{part.index}"
        with self._part_lock(key):
            return self._upload_part_unlocked(target, session, part)

    def _part_lock(self, key: str) -> threading.Lock:
        with self._part_locks_guard:
            return self._part_locks.setdefault(key, threading.Lock())

    def _upload_part_unlocked(
        self,
        target: TargetConfig,
        session: SessionRecord,
        part: SessionPart,
    ) -> CloudUploadResult:
        cancel_event = self._cancel_event(f"{session.session_id}:{part.index}")
        if not target.cloud_backup:
            return CloudUploadResult(False, [], ["cloud backup disabled"])
        remote_root = self._validate_remote(target.cloud_remote)
        files = self._part_files(part)
        if not files:
            raise CloudUploadError(f"P{part.index:02d} has no local files to back up")

        remote_dir = self.part_remote_dir(target, session, part, remote_root)
        uploaded_paths: list[str] = []
        messages: list[str] = []
        api_client = self._openlist_api_client(remote_root)
        for local_path in files:
            if cancel_event.is_set():
                raise CloudUploadError("网盘备份已停止")
            remote_path = f"{remote_dir}/{local_path.name}"
            if api_client is not None:
                try:
                    api_client.upload(local_path, remote_path, cancel_event)
                except OpenListApiError as exc:
                    raise CloudUploadError(str(exc)) from exc
                uploaded_paths.append(remote_path)
                continue
            command = [
                self.config.cloud_rclone_bin,
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
            ]
            try:
                result = self.runner.run(
                    command,
                    cancel_event=cancel_event,
                    timeout_seconds=self.config.cloud_upload_timeout_seconds,
                )
            except FileNotFoundError as exc:
                self.reset_cancel(f"{session.session_id}:{part.index}")
                raise CloudUploadError(
                    f"rclone 不存在或不可执行：{self.config.cloud_rclone_bin}"
                ) from exc
            messages.extend(result.lines)
            if result.cancelled:
                raise CloudUploadError("网盘备份已停止")
            if result.timed_out:
                raise CloudUploadError(f"网盘上传超时：{local_path.name}")
            if result.returncode != 0:
                detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
                raise CloudUploadError(f"网盘上传失败：{local_path.name}：{detail}")
            uploaded_paths.append(remote_path)
        self.reset_cancel(f"{session.session_id}:{part.index}")
        return CloudUploadResult(True, uploaded_paths, messages)

    def cancel(self, key: str) -> None:
        self._cancel_event(key).set()

    def reset_cancel(self, key: str) -> None:
        with self._cancel_lock:
            self._cancel_events.pop(key, None)

    def _openlist_api_client(self, remote: str) -> OpenListApiClient | None:
        if remote not in self._api_clients:
            self._api_clients[remote] = OpenListApiClient.from_rclone_remote(
                remote,
                rclone_bin=self.config.cloud_rclone_bin,
                timeout_seconds=self.config.cloud_upload_timeout_seconds,
            )
        return self._api_clients[remote]

    def _cancel_event(self, key: str) -> threading.Event:
        with self._cancel_lock:
            return self._cancel_events.setdefault(key, threading.Event())

    def ensure_anchor_dir(
        self,
        target_name: str,
        remote: str,
        *,
        rclone_bin: str | None = None,
    ) -> str:
        remote_root = self._validate_remote(remote)
        anchor = safe_path_name(target_name, "未命名主播")
        remote_path = f"{remote_root}/{anchor}"
        list_command = [
            rclone_bin or self.config.cloud_rclone_bin,
            "lsf",
            remote_root,
            "--max-depth",
            "1",
            "--dirs-only",
        ]
        try:
            listed = self.runner.run(list_command, timeout_seconds=60)
        except FileNotFoundError as exc:
            raise CloudUploadError(
                f"rclone 不存在或不可执行：{list_command[0]}"
            ) from exc
        if listed.cancelled:
            raise CloudUploadError("检查网盘主播目录已停止")
        if listed.timed_out:
            raise CloudUploadError("检查网盘主播目录超时")
        entries = {line.strip().rstrip("/") for line in listed.lines if line.strip()}
        if listed.returncode == 0 and anchor in entries:
            return remote_path
        command = [rclone_bin or self.config.cloud_rclone_bin, "mkdir", remote_path]
        try:
            result = self.runner.run(command, timeout_seconds=60)
        except FileNotFoundError as exc:
            raise CloudUploadError(
                f"rclone 不存在或不可执行：{command[0]}"
            ) from exc
        if result.cancelled:
            raise CloudUploadError("创建网盘主播目录已停止")
        if result.timed_out:
            raise CloudUploadError("创建网盘主播目录超时")
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudUploadError(f"创建网盘主播目录失败：{detail}")
        return remote_path

    def test_remote(self, remote: str) -> CloudUploadResult:
        remote_root = self._validate_remote(remote)
        command = [
            self.config.cloud_rclone_bin,
            "lsf",
            remote_root,
            "--max-depth",
            "1",
        ]
        try:
            result = self.runner.run(command, timeout_seconds=60)
        except FileNotFoundError as exc:
            raise CloudUploadError(
                f"rclone 不存在或不可执行：{self.config.cloud_rclone_bin}"
            ) from exc
        if result.returncode != 0:
            detail = result.lines[-1] if result.lines else f"exit code {result.returncode}"
            raise CloudUploadError(f"网盘远端不可访问：{detail}")
        return CloudUploadResult(True, [remote_root], result.lines)

    def part_remote_dir(
        self,
        target: TargetConfig,
        session: SessionRecord,
        part: SessionPart,
        remote_root: str | None = None,
    ) -> str:
        root = self._validate_remote(remote_root or target.cloud_remote)
        anchor = safe_path_name(target.name, "未命名主播")
        date = session.detected_start_iso or ""
        date_part = date[:10] if len(date) >= 10 else "unknown-date"
        return f"{root}/{anchor}/{date_part}"

    @staticmethod
    def _part_files(part: SessionPart) -> list[Path]:
        candidates = [part.path]
        paths: list[Path] = []
        seen: set[str] = set()
        for value in candidates:
            if not value:
                continue
            path = Path(value)
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen or not path.exists() or not path.is_file():
                continue
            seen.add(key)
            paths.append(path)
        return paths

    @staticmethod
    def _validate_remote(remote: str) -> str:
        value = remote.strip().rstrip("/")
        if not value or ":" not in value:
            raise CloudUploadError("网盘远端必须使用 rclone 格式，例如 openlist:/DouyinBiliRecorder")
        name = value.split(":", 1)[0].strip()
        if not name:
            raise CloudUploadError("网盘远端缺少 rclone remote 名称")
        return value

    @staticmethod
    def detect_provider(remote: str) -> str:
        name = PurePosixPath(remote.split(":", 1)[0]).name.lower()
        if "baidu" in name or "pan" in name:
            return "baidu"
        if "quark" in name or "uc" in name:
            return "quark"
        return "custom"
