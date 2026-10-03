from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .cloud import CloudDriver, CloudDriverError, DriverContext, create_driver
from .cloud.driver import detect_provider as _detect_provider
from .config import AppConfig, TargetConfig
from .models import SessionPart, SessionRecord
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
    """Backs up finished parts through the best available cloud driver.

    The public API is unchanged from the rclone-only implementation; the
    actual transfer is delegated to a driver (Quark CLI, Baidu CLI, OpenList or
    plain rclone) chosen by :mod:`douyin_bili_recorder.cloud`.
    """

    def __init__(self, config: AppConfig, runner: ProcessRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger
        self._cancel_lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._part_locks: dict[str, threading.Lock] = {}
        self._part_locks_guard = threading.Lock()
        self._drivers: dict[str, CloudDriver] = {}
        self._drivers_guard = threading.Lock()

    # ------------------------------------------------------------------ public

    def upload_part(
        self,
        target: TargetConfig,
        session: SessionRecord,
        part: SessionPart,
    ) -> CloudUploadResult:
        key = f"{session.session_id}:{part.index}"
        with self._part_lock(key):
            return self._upload_part_unlocked(target, session, part)

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
        driver = self._driver(remote_root, target_name)
        try:
            driver.ensure_dir(remote_path, threading.Event())
        except CloudDriverError as exc:
            raise CloudUploadError(str(exc)) from exc
        return remote_path

    def test_remote(self, remote: str) -> CloudUploadResult:
        remote_root = self._validate_remote(remote)
        driver = self._driver(remote_root, remote_root)
        try:
            lines = driver.probe(remote_root)
        except CloudDriverError as exc:
            raise CloudUploadError(str(exc)) from exc
        return CloudUploadResult(True, [remote_root], lines)

    def driver_info(self, remote: str) -> dict[str, object]:
        driver = self._driver(remote, remote)
        return {
            "driver": driver.name,
            "capabilities": driver.capabilities.to_dict(),
            "remote": remote,
        }

    def cancel(self, key: str) -> None:
        self._cancel_event(key).set()

    def reset_cancel(self, key: str) -> None:
        with self._cancel_lock:
            self._cancel_events.pop(key, None)

    # ----------------------------------------------------------------- internal

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
        provider = target.cloud_provider or _detect_provider(remote_root)
        driver = self._driver(remote_root, provider, provider=provider)
        uploaded_paths: list[str] = []
        messages: list[str] = []
        try:
            driver.ensure_dir(remote_dir, cancel_event)
        except CloudDriverError as exc:
            raise CloudUploadError(str(exc)) from exc
        for local_path in files:
            if cancel_event.is_set():
                raise CloudUploadError("网盘备份已停止")
            remote_path = f"{remote_dir}/{local_path.name}"
            try:
                outcome = driver.upload(local_path, remote_path, cancel_event)
            except CloudDriverError as exc:
                raise CloudUploadError(str(exc)) from exc
            uploaded_paths.extend(outcome.remote_paths)
            messages.extend(outcome.messages)
        self.reset_cancel(f"{session.session_id}:{part.index}")
        return CloudUploadResult(True, uploaded_paths, messages)

    def _driver(
        self,
        remote: str,
        cache_key: str,
        *,
        provider: str | None = None,
    ) -> CloudDriver:
        key = f"{provider or _detect_provider(remote)}|{cache_key}|{remote}"
        with self._drivers_guard:
            cached = self._drivers.get(key)
            if cached is not None:
                return cached
            context = DriverContext(config=self.config, runner=self.runner, logger=self.logger)
            try:
                driver = create_driver(provider or _detect_provider(remote), remote, context)
            except CloudDriverError as exc:
                raise CloudUploadError(str(exc)) from exc
            self._drivers[key] = driver
            self.logger.info(
                "cloud driver for %s: %s (%s)",
                remote,
                driver.name,
                driver.capabilities.notes or "no notes",
            )
            return driver

    def _part_lock(self, key: str) -> threading.Lock:
        with self._part_locks_guard:
            return self._part_locks.setdefault(key, threading.Lock())

    def _cancel_event(self, key: str) -> threading.Event:
        with self._cancel_lock:
            return self._cancel_events.setdefault(key, threading.Event())

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
