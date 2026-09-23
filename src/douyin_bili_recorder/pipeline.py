from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import AppConfig, TargetConfig
from .media import MediaProcessor
from .models import SessionRecord, SessionStatus
from .process import ProcessRunner
from .recorder import BiliupRecorder, discover_media
from .state import SessionStore, SingleInstanceLock, slugify
from .timeutil import build_title, epoch_iso
from .uploader import BiliupUploader


class RecorderService:
    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        shutdown_event: threading.Event | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.shutdown_event = shutdown_event or threading.Event()
        self.store = SessionStore(config.sessions_dir)
        self.runner = ProcessRunner(logger, self.shutdown_event)
        self.recorder = BiliupRecorder(config, self.runner, logger)
        self.media = MediaProcessor(config, self.runner, logger)
        self.uploader = BiliupUploader(config, self.runner, logger)

    def run_forever(self) -> None:
        self.config.sessions_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.config.data_dir / "recorder.lock"
        with SingleInstanceLock(lock_path):
            self.recover_pending()
            targets = [target for target in self.config.targets if target.enabled]
            if not targets:
                self.logger.warning("no enabled targets configured")
                return
            with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix="target") as pool:
                futures = [pool.submit(self._target_loop, target) for target in targets]
                for future in futures:
                    future.result()

    def run_once(self, target_name: str | None = None) -> bool:
        target = self._select_target(target_name)
        self.recover_pending()
        return self.record_and_upload(target)

    def status(self) -> list[SessionRecord]:
        return sorted(self.store.all(), key=lambda item: item.created_epoch, reverse=True)

    def recover_pending(self) -> None:
        for session in self.store.all():
            if session.status == SessionStatus.RECORDING:
                session.status = SessionStatus.RECORDED
                session.ended_epoch = session.ended_epoch or int(time.time())
                self.store.save(session)
            if session.status in {
                SessionStatus.RECORDED,
                SessionStatus.UPLOADING,
                SessionStatus.UPLOAD_FAILED,
            }:
                self._upload_with_retries(session)
            elif session.status == SessionStatus.UPLOAD_SUBMITTED_UNVERIFIED:
                target = self._target_by_name(session.target_name)
                if target is not None:
                    bvid = self.uploader.find_bvid_by_title(session.title)
                    if bvid:
                        session.bvid = bvid
                        session.status = SessionStatus.UPLOADED
                        session.error = ""
                        self.store.save(session)

    def _target_loop(self, target: TargetConfig) -> None:
        while not self.shutdown_event.is_set():
            try:
                self.record_and_upload(target)
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("target loop failed for %s: %s", target.name, exc)
            self.shutdown_event.wait(self.config.poll_interval_seconds)

    def record_and_upload(self, target: TargetConfig) -> bool:
        session = self._new_session(target)
        session_dir = self.store.session_dir(session.session_id)
        self.store.save(session)
        media_found = False
        attempts = 0

        while not self.shutdown_event.is_set():
            attempts += 1
            session.attempts = attempts
            session.status = SessionStatus.RECORDING
            self.store.save(session)
            attempt_started = int(time.time())
            attempt = self.recorder.record(target, session_dir)
            attempt_media = discover_media(session_dir, self.config.min_file_size_mb)
            media_found = media_found or bool(attempt_media)

            if media_found and session.detected_start_epoch is None:
                session.detected_start_epoch = attempt_started
                session.detected_start_iso = epoch_iso(attempt_started, self.config.timezone)
                self.store.save(session)

            if attempt.stream_offline:
                self.logger.info("target %s is offline", target.name)
                break
            if attempt.returncode == 0:
                break
            if attempts > self.config.max_reconnect_attempts:
                self.logger.error("target %s exceeded reconnect attempts", target.name)
                break

            self.shutdown_event.wait(self.config.reconnect_backoff_seconds)

        if not media_found:
            self.store.delete(session.session_id)
            return False

        session.status = SessionStatus.RECORDED
        session.ended_epoch = int(time.time())
        session.files = self.media.process(session_dir)
        self.store.save(session)
        self._upload_with_retries(session)
        return True

    def _upload_with_retries(self, session: SessionRecord) -> None:
        target = self._target_by_name(session.target_name)
        if target is None:
            session.status = SessionStatus.FAILED
            session.error = f"target no longer exists: {session.target_name}"
            self.store.save(session)
            return

        session_dir = self.config.sessions_dir / session.session_id
        session.title = build_title(
            target.title_template,
            target.name,
            target.url,
            session,
            self.config.timezone,
        )
        self.store.save(session)

        for attempt in range(self.config.upload_retry_count + 1):
            session.status = SessionStatus.UPLOADING
            session.attempts = attempt
            self.store.save(session)
            try:
                result = self.uploader.upload_session(target, session, session_dir, title=session.title)
                session.bvid = result.bvid
                session.error = ""
                if result.verified:
                    session.status = SessionStatus.UPLOADED
                    self.store.save(session)
                    self.logger.info("session %s uploaded as %s", session.session_id, result.bvid)
                    if self.config.delete_after_upload:
                        self.store.delete(session.session_id)
                    return
                session.status = SessionStatus.UPLOAD_SUBMITTED_UNVERIFIED
                session.error = "submission was sent but BVID was not verified"
                self.store.save(session)
                return
            except Exception as exc:  # noqa: BLE001
                session.error = str(exc)
                session.status = SessionStatus.UPLOAD_FAILED
                self.store.save(session)
                self.logger.exception("upload failed for %s", session.session_id)
                if attempt < self.config.upload_retry_count:
                    self.shutdown_event.wait(self.config.upload_retry_backoff_seconds * (attempt + 1))

    def _new_session(self, target: TargetConfig) -> SessionRecord:
        now = datetime.now(ZoneInfo(self.config.timezone))
        session_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{slugify(target.name)}"
        return SessionRecord(
            session_id=session_id,
            target_name=target.name,
            target_url=target.url,
            created_epoch=int(now.timestamp()),
            detected_start_epoch=int(now.timestamp()),
            detected_start_iso=now.isoformat(timespec="seconds"),
            title="",
        )

    def _target_by_name(self, name: str) -> TargetConfig | None:
        return next((item for item in self.config.targets if item.name == name), None)

    def _select_target(self, name: str | None) -> TargetConfig:
        if name:
            target = self._target_by_name(name)
            if target is None:
                raise ValueError(f"unknown target: {name}")
            return target
        target = next((item for item in self.config.targets if item.enabled), None)
        if target is None:
            raise ValueError("no enabled targets configured")
        return target

    def stop(self) -> None:
        self.shutdown_event.set()
        self.runner.terminate_active()
