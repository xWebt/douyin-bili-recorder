from __future__ import annotations

import json

import logging
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, TargetConfig
from .models import SessionRecord
from .process import ProcessRunner
from .timeutil import build_title
from .upload_progress import UploadProgressSampler, UploadProgressStore

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BVID_RE = re.compile(r"\bBV[0-9A-Za-z]{10}\b")


@dataclass(slots=True)
class UploadResult:
    bvid: str | None
    verified: bool
    messages: list[str]


class UploadRateLimited(RuntimeError):
    pass


class UploadCancelled(RuntimeError):
    pass


class BiliupUploader:
    def __init__(self, config: AppConfig, runner: ProcessRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger
        self.progress_store = UploadProgressStore(config.data_dir)
        self._cancel_lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._submit_lock = threading.Lock()
        self._next_submit_at = 0.0
        self._bvid_cache_lock = threading.Lock()
        self._bvid_cache: dict[str, str] = {}
        self._bvid_cache_at = 0.0

    def upload_session(
        self,
        target: TargetConfig,
        session: SessionRecord,
        session_dir: Path,
        title: str | None = None,
    ) -> UploadResult:
        files = session.media_paths(session_dir)
        if not files:
            raise RuntimeError(f"session {session.session_id} has no media to upload")
        if not self.config.cookie_file.exists():
            raise RuntimeError(f"Bilibili cookie file does not exist: {self.config.cookie_file}")

        resolved_title = title or build_title(
            target.title_template,
            target.name,
            target.url,
            session,
            self.config.timezone,
        )
        source = target.source or target.url

        existing = self.find_bvid_by_title(resolved_title)
        if existing:
            self.logger.info("submission already exists for title %s: %s", resolved_title, existing)
            return UploadResult(existing, True, ["submission already exists"])

        first = files[0]
        command = self._upload_command(
            target,
            session,
            first,
            resolved_title,
            description=self._description(target, session),
            source=source,
        )
        result = self._run_upload_command(
            command,
            media_path=first,
            target=target,
            session_id=session.session_id,
            part_index=1,
            title=resolved_title,
        )
        messages = list(result.lines)
        if result.returncode != 0:
            raise RuntimeError(f"Bilibili submission command failed with code {result.returncode}")

        bvid = self._wait_for_bvid(resolved_title)
        if not bvid:
            return UploadResult(None, False, messages + ["submission was sent but BVID lookup timed out"])
        self._mark_progress_complete(bvid, f"{session.session_id}:1")

        for index, media_path in enumerate(files[1:], start=2):
            part_title = f"{target.name}｜{session.detected_start_iso or session.session_id}｜P{index:02d}"
            append_command = self._append_command(
                target,
                session,
                media_path,
                bvid,
                part_title,
                description=self._description(target, session),
                source=source,
            )
            append_result = self._run_upload_command(
                append_command,
                media_path=media_path,
                target=target,
                session_id=session.session_id,
                part_index=index,
                title=part_title,
                existing_bvid=bvid,
            )
            messages.extend(append_result.lines)
            if append_result.returncode != 0:
                raise RuntimeError(f"failed to append {media_path.name} to {bvid}")

        return UploadResult(bvid, True, messages)

    def upload_part(
        self,
        target: TargetConfig,
        session: SessionRecord,
        media_path: Path,
        *,
        part_index: int,
        title: str,
        bvid: str | None = None,
    ) -> UploadResult:
        if not self.config.cookie_file.exists():
            raise RuntimeError(f"Bilibili cookie file does not exist: {self.config.cookie_file}")
        source = target.source or target.url
        description = self._description(target, session)
        existing = self.find_bvid_by_title(title)
        if existing:
            return UploadResult(existing, True, ["submission already exists"])
        if bvid:
            command = self._append_command(
                target,
                session,
                media_path,
                bvid,
                title,
                description=description,
                source=source,
            )
            result = self._run_upload_command(
                command,
                media_path=media_path,
                target=target,
                session_id=session.session_id,
                part_index=part_index,
                title=title,
                existing_bvid=bvid,
            )
            if result.returncode != 0:
                if result.cancelled:
                    raise UploadCancelled("上传已由用户停止")
                if self._is_rate_limited(result.lines):
                    raise UploadRateLimited("B站投稿频率限制，请稍后重试")
                raise RuntimeError(f"Bilibili append command failed with code {result.returncode}")
            self._mark_progress_complete(bvid, f"{session.session_id}:{part_index}")
            return UploadResult(bvid, True, list(result.lines))

        command = self._upload_command(
            target,
            session,
            media_path,
            title,
            description=description,
            source=source,
        )
        result = self._run_upload_command(
            command,
            media_path=media_path,
            target=target,
            session_id=session.session_id,
            part_index=part_index,
            title=title,
        )
        if result.returncode != 0:
            if result.cancelled:
                raise UploadCancelled("上传已由用户停止")
            if self._is_rate_limited(result.lines):
                raise UploadRateLimited("B站投稿频率限制，请稍后重试")
            raise RuntimeError(f"Bilibili submission command failed with code {result.returncode}")
        found = self._wait_for_bvid(title)
        if found:
            self._mark_progress_complete(found, f"{session.session_id}:{part_index}")
        return UploadResult(found, bool(found), list(result.lines))

    def _upload_command(
        self,
        target: TargetConfig,
        session: SessionRecord,
        media_path: Path,
        title: str,
        *,
        description: str,
        source: str,
    ) -> list[str]:
        command = [
            self.config.biliup_bin,
            "-u",
            str(self.config.cookie_file),
            "upload",
            str(media_path),
            "--line",
            self.config.upload_line,
            "--title",
            title,
            "--desc",
            description,
            "--copyright",
            str(target.copyright),
            "--source",
            source,
            "--tid",
            str(target.tid),
            "--tag",
            ",".join(target.tags),
            *self._collection_extra_args(target),
        ]
        if not target.public:
            command.extend(["--is-only-self", "1"])
        return command

    def _append_command(
        self,
        target: TargetConfig,
        session: SessionRecord,
        media_path: Path,
        bvid: str,
        title: str,
        *,
        description: str,
        source: str,
    ) -> list[str]:
        command = [
            self.config.biliup_bin,
            "-u",
            str(self.config.cookie_file),
            "append",
            "--vid",
            bvid,
            "--line",
            self.config.upload_line,
            str(media_path),
            "--title",
            title,
            "--desc",
            description,
            "--copyright",
            str(target.copyright),
            "--source",
            source,
            "--tid",
            str(target.tid),
            "--tag",
            ",".join(target.tags),
            *self._collection_extra_args(target),
        ]
        if not target.public:
            command.extend(["--is-only-self", "1"])
        return command

    def _run_upload_command(
        self,
        command: list[str],
        *,
        media_path: Path,
        target: TargetConfig,
        session_id: str,
        part_index: int,
        title: str,
        existing_bvid: str | None = None,
    ):
        with self._submission_slot():
            return self._run_upload_command_unlocked(
                command,
                media_path=media_path,
                target=target,
                session_id=session_id,
                part_index=part_index,
                title=title,
                existing_bvid=existing_bvid,
            )

    def _run_upload_command_unlocked(
        self,
        command: list[str],
        *,
        media_path: Path,
        target: TargetConfig,
        session_id: str,
        part_index: int,
        title: str,
        existing_bvid: str | None = None,
    ):
        progress_key = f"{session_id}:{part_index}"
        progress = UploadProgressSampler(self.progress_store, self.logger, progress_key)
        progress.start(
            media_path,
            target_name=target.name,
            title=title,
            part_index=part_index,
            total_bytes=media_path.stat().st_size,
        )
        cancel_event = self._cancel_event(progress_key)
        result = None
        try:
            result = self.runner.run(command, cancel_event=cancel_event)
        finally:
            if result is None or result.returncode != 0:
                message = "上传失败"
            else:
                message = "上传完成" if existing_bvid else "等待 BVID"
            progress.stop(message=message, bvid=existing_bvid)
        self.invalidate_bvid_cache()
        return result

    @contextmanager
    def _submission_slot(self):
        with self._submit_lock:
            interval = max(0, self.config.upload_submit_interval_seconds)
            while interval:
                wait = self._next_submit_at - time.monotonic()
                if wait <= 0:
                    break
                shutdown = getattr(self.runner, "shutdown_event", None)
                if shutdown is not None:
                    if shutdown.wait(min(wait, 1.0)):
                        raise UploadCancelled("上传已停止")
                else:
                    time.sleep(min(wait, 1.0))
            try:
                yield
            finally:
                self._next_submit_at = time.monotonic() + interval

    @staticmethod
    def _is_rate_limited(lines: list[str]) -> bool:
        text = "\n".join(lines)
        return any(
            marker in text
            for marker in (
                "21566",
                "601",
                "投稿过于频繁",
                "上传视频过快",
                "request limited",
                "Failed to pre_upload",
            )
        )

    def cancel(self, key: str) -> None:
        self._cancel_event(key).set()

    def reset_cancel(self, key: str) -> None:
        with self._cancel_lock:
            self._cancel_events.pop(key, None)

    def _cancel_event(self, key: str) -> threading.Event:
        with self._cancel_lock:
            return self._cancel_events.setdefault(key, threading.Event())

    def _mark_progress_complete(self, bvid: str, progress_key: str) -> None:
        payload = next(
            (item for item in self.progress_store.load_all() if item.get("key") == progress_key),
            {},
        )
        if not payload:
            return
        payload["available"] = True
        payload["message"] = "上传完成"
        payload["percent"] = 100
        payload["uploaded_bytes"] = payload.get("total_bytes", payload.get("uploaded_bytes", 0))
        payload["eta_seconds"] = 0
        payload["bvid"] = bvid
        payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.progress_store.upsert(progress_key, payload)

    def find_bvid_by_title(self, title: str) -> str | None:
        with self._bvid_cache_lock:
            if time.monotonic() - self._bvid_cache_at < 15:
                return self._bvid_cache.get(title)
        command = [self.config.biliup_bin, "-u", str(self.config.cookie_file), "list"]
        completed = self.runner.run(command)
        discovered: dict[str, str] = {}
        for line in completed.lines:
            clean = ANSI_RE.sub("", line)
            match = BVID_RE.search(clean)
            if match:
                fields = clean.split("\t")
                if len(fields) >= 2:
                    discovered[fields[1].strip()] = match.group(0)
        with self._bvid_cache_lock:
            self._bvid_cache = discovered
            self._bvid_cache_at = time.monotonic()
            return discovered.get(title)

    def invalidate_bvid_cache(self) -> None:
        with self._bvid_cache_lock:
            self._bvid_cache = {}
            self._bvid_cache_at = 0.0

    def _wait_for_bvid(self, title: str) -> str | None:
        attempts = 10
        for index in range(attempts):
            bvid = self.find_bvid_by_title(title)
            if bvid:
                return bvid
            if index < attempts - 1:
                time.sleep(3)
        return None

    def _description(self, target: TargetConfig, session: SessionRecord) -> str:
        source = target.source or target.url
        start = session.detected_start_iso or "unknown"
        return (
            f"抖音直播录制\n"
            f"主播：{target.name}\n"
            f"开播检测时间：{start}\n"
            f"来源：{source}"
        )

    def _collection_extra_args(self, target: TargetConfig) -> list[str]:
        collection_id = str(target.collection_id or "").strip()
        if not collection_id:
            return []
        try:
            value: int | str = int(collection_id)
        except ValueError:
            value = collection_id
        return ["--extra-fields", json.dumps({"season_id": value}, ensure_ascii=False)]
