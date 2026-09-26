from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import Future, wait
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .analytics import AnalyticsStore
from .collection import BilibiliCollectionManager
from .config import AppConfig, TargetConfig, load_config
from .douyin import DouyinResolver
from .danmaku import DanmakuRenderer
from .encoding import peak_gb_per_segment
from .media import MediaProcessor
from .models import MediaFile, SessionPart, SessionRecord, SessionStatus
from .paths import safe_path_name, session_output_dir, target_key
from .process import ProcessRunner
from .recorder import BiliupRecorder, discover_media
from .scheduling import active_slot, expected_start_for_moment, is_late_detection, next_poll_delay_seconds, should_poll_now
from .state import SessionStore, SingleInstanceLock, slugify
from .storage_guard import StorageGuard
from .timeutil import build_title, epoch_iso, parse_duration_seconds
from .ui_state import UIStateStore
from .uploader import BiliupUploader, UploadResult


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
        self.interrupt_event = threading.Event()
        self.store = SessionStore(config.sessions_dir)
        self.record_runner = ProcessRunner(logger, self.shutdown_event, self.interrupt_event)
        self.io_runner = ProcessRunner(logger, self.shutdown_event)
        self.recorder = BiliupRecorder(config, self.record_runner, logger)
        self.media = MediaProcessor(config, self.io_runner, logger)
        self.danmaku = DanmakuRenderer(config, self.io_runner, logger)
        self.uploader = BiliupUploader(config, self.io_runner, logger)
        self.storage = StorageGuard(config.sessions_dir, logger)
        self.analytics = AnalyticsStore(config.video_dir, config.timezone)
        self.resolver = DouyinResolver()
        self._pause_mode = ""
        self._state_lock = threading.Lock()
        upload_workers = max(1, min(8, len([target for target in config.targets if target.enabled])))
        self.upload_executor = ThreadPoolExecutor(max_workers=upload_workers, thread_name_prefix="upload")
        self._pending_uploads: dict[str, list[Future[bool]]] = {}

    def run_forever(self) -> None:
        self._start_external_stop_watcher()
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
                self.analytics.upsert(session)
            if session.status in {SessionStatus.RECORDED, SessionStatus.UPLOADING, SessionStatus.UPLOAD_FAILED}:
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
                self._reload_runtime_settings(target)
                if not target.enabled:
                    if self._wait_for_stop(max(10, self.config.poll_interval_seconds)):
                        break
                    continue
                if target.watch_mode == "manual":
                    if not self._consume_manual_request(target):
                        if self._wait_for_stop(2):
                            break
                        continue
                now = datetime.now(ZoneInfo(self.config.timezone))
                if target.watch_mode == "scheduled" and (
                    not target.schedule or not should_poll_now(target.schedule, now)
                ):
                    if self._wait_for_stop(next_poll_delay_seconds(target.schedule, now)):
                        break
                    continue
                self.record_and_upload(target)
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("target loop failed for %s: %s", target.name, exc)
            now = datetime.now(ZoneInfo(self.config.timezone))
            delay = next_poll_delay_seconds(
                target.schedule,
                now,
                inside_seconds=self.config.poll_interval_seconds,
                outside_seconds=min(900, max(60, self.config.poll_interval_seconds * 2)),
            )
            if self._wait_for_stop(delay):
                break

    def record_and_upload(self, target: TargetConfig) -> bool:
        self._reload_runtime_settings(target)
        if target.record_mode == "monitor":
            return self._monitor_target(target)
        if target.record_danmaku and not self._is_live(target):
            return False
        if not self._wait_for_capacity(target):
            return False

        session = self._new_session(target)
        session_dir = self.store.session_dir(session.session_id)
        self.store.save(session)
        self.analytics.upsert(session)

        segment_seconds = parse_duration_seconds(self.config.segment_time)
        seen_sources: set[str] = set()
        part_index = 1
        final_status = SessionStatus.RECORDED
        upload_futures: list[Future[bool]] = []

        while not self.shutdown_event.is_set() and not self.interrupt_event.is_set():
            self._reload_runtime_settings(target)
            if not self._wait_for_capacity(target):
                final_status = SessionStatus.UPLOAD_FAILED
                session.error = "space budget is insufficient for the next segment"
                break

            process = self.recorder.start(target, session_dir)
            connection_started = int(time.time())
            media_found = False

            while not self.shutdown_event.is_set() and not self.interrupt_event.is_set():
                new_media = self._new_media_paths(
                    session_dir,
                    seen_sources,
                    allow_partials=False,
                )
                if new_media:
                    media_found = True
                    self._mark_recording_started(target, session, connection_started)
                    part_index = self._process_media_batch(
                        target,
                        session,
                        session_dir,
                        new_media,
                        seen_sources,
                        part_index,
                        upload_futures,
                    )
                if process.poll() is not None:
                    break
                if self._process_reports_offline(process):
                    process.terminate()
                    break
                self.shutdown_event.wait(2)

            tail_media = self._final_media_paths(
                session_dir,
                seen_sources,
            )
            if tail_media:
                media_found = True
                self._mark_recording_started(target, session, connection_started)
                part_index = self._process_media_batch(
                    target,
                    session,
                    session_dir,
                    tail_media,
                    seen_sources,
                    part_index,
                    upload_futures,
                )

            if self.interrupt_event.is_set():
                break
            offline = self._process_reports_offline(process)
            if offline or process.poll() != 0 or not media_found:
                ever_recorded = session.detected_start_epoch is not None
                if not media_found and not ever_recorded:
                    self.logger.info("offline probe completed quickly for %s", target.name)
                    break
                session.last_seen_live_epoch = connection_started
                self.store.save(session)
                if self._wait_for_reconnect(target, session):
                    continue
                break
            self.shutdown_event.wait(0.25)
            continue

        self._wait_for_uploads(session.session_id, upload_futures)
        if session.parts and all(part.status == "UPLOADED" for part in session.parts):
            final_status = SessionStatus.UPLOADED
        session.status = final_status
        session.ended_epoch = int(time.time())
        self.store.save(session)
        self.analytics.upsert(session)
        self.storage.enforce_limit(self.config.max_cache_gb)
        remaining_files = [
            path
            for path in session_dir.iterdir()
            if path.name not in {"session.json", ".danmaku-runtime"}
        ]
        if not session.parts and not remaining_files:
            self.store.delete(session.session_id)
            if self.interrupt_event.is_set():
                self.shutdown_event.set()
            return False
        if self.interrupt_event.is_set():
            self.shutdown_event.set()
        return bool(session.parts or final_status == SessionStatus.UPLOADED)

    def _monitor_target(self, target: TargetConfig) -> bool:
        self._reload_runtime_settings(target)
        if not self._is_live(target):
            return False
        status = self._resolve_status(target)
        session = self._new_session(target)
        session.record_mode = "monitor"
        session.detected_start_epoch = int(time.time())
        session.detected_start_iso = epoch_iso(session.detected_start_epoch, self.config.timezone)
        session.room_title = status.room_title if status is not None else ""
        self._apply_schedule(target, session, session.detected_start_epoch)
        session.status = SessionStatus.RECORDING
        self.store.save(session)
        self.analytics.upsert(session)

        last_seen = session.detected_start_epoch
        reconnect_started_at: int | None = None
        while not self.shutdown_event.is_set() and not self.interrupt_event.is_set():
            self.shutdown_event.wait(max(5, self.config.poll_interval_seconds))
            if self._is_live(target):
                current = self._resolve_status(target)
                last_seen = int(time.time())
                session.last_seen_live_epoch = last_seen
                reconnect_started_at = None
                session.room_title = (current.room_title if current is not None else "") or session.room_title
                self.store.save(session)
                continue
            reconnect_started_at = reconnect_started_at or int(time.time())
            if int(time.time()) - reconnect_started_at <= self.config.reconnect_grace_minutes * 60:
                continue
            break

        session.status = SessionStatus.RECORDED
        session.ended_epoch = last_seen
        self.store.save(session)
        self.analytics.upsert(session)
        if self.interrupt_event.is_set():
            self.shutdown_event.set()
        return True

    def _new_media_paths(
        self,
        session_dir: Path,
        seen_sources: set[str],
        *,
        allow_partials: bool,
    ) -> list[Path]:
        return [
            path
            for path in discover_media(
                session_dir,
                self.config.min_file_size_mb,
                allow_partials=allow_partials,
            )
            if str(path) not in seen_sources
        ]

    def _mark_recording_started(self, target: TargetConfig, session: SessionRecord, started_epoch: int) -> None:
        if session.detected_start_epoch is None:
            session.detected_start_epoch = started_epoch
            session.detected_start_iso = epoch_iso(started_epoch, self.config.timezone)
            self._apply_schedule(target, session, started_epoch)
        if not session.room_title:
            status = self._resolve_status(target)
            if status is not None:
                session.room_title = status.room_title or session.room_title
        session.status = SessionStatus.RECORDING
        self.store.save(session)
        self.analytics.upsert(session)

    def _process_media_batch(
        self,
        target: TargetConfig,
        session: SessionRecord,
        session_dir: Path,
        media_paths: list[Path],
        seen_sources: set[str],
        part_index: int,
        upload_futures: list[Future[bool]],
    ) -> int:
        for source in media_paths:
            seen_sources.add(str(source))
            upload_allowed = self.pause_mode() != "keep"
            part = self._prepare_part(
                target,
                session,
                session_dir,
                source,
                part_index,
                upload_allowed=upload_allowed,
            )
            if part is None:
                session.error = f"failed to prepare part {part_index}"
                self.store.save(session)
                continue
            if part.status == "PENDING":
                future = self.upload_executor.submit(
                    self._upload_part_job,
                    target,
                    session,
                    part,
                )
                upload_futures.append(future)
                self._pending_uploads.setdefault(session.session_id, []).append(future)
            part_index += 1
        return part_index

    def _final_media_paths(
        self,
        session_dir: Path,
        seen_sources: set[str],
    ) -> list[Path]:
        result: list[Path] = []
        for path in self._new_media_paths(session_dir, seen_sources, allow_partials=True):
            try:
                has_data = path.stat().st_size > 0
            except OSError:
                has_data = False
            if has_data:
                result.append(path)
            else:
                path.unlink(missing_ok=True)
        return result

    @staticmethod
    def _process_reports_offline(process) -> bool:
        text = "\n".join(process.output()).lower()
        return "stream is offline" in text or "stream went offline" in text

    def _wait_for_capacity(self, target: TargetConfig) -> bool:
        segment_seconds = parse_duration_seconds(self.config.segment_time)
        peak = peak_gb_per_segment(
            self.config.quality,
            self.config.frame_rate,
            segment_seconds=segment_seconds,
            burn_danmaku=target.record_danmaku,
        )
        while not self.shutdown_event.is_set() and not self.interrupt_event.is_set():
            self.storage.enforce_limit(self.config.max_cache_gb)
            usage = self._managed_usage_bytes() / (1024**3)
            self.config.video_dir.mkdir(parents=True, exist_ok=True)
            free_gb = shutil.disk_usage(self.config.video_dir).free / (1024**3)
            if usage + peak <= self.config.max_cache_gb:
                if free_gb >= peak + 1:
                    return True
                self.logger.warning(
                    "physical disk free space is too low for %s: free %.2f GB, need %.2f GB",
                    target.name,
                    free_gb,
                    peak + 1,
                )
            active = any(
                not future.done()
                for futures in self._pending_uploads.values()
                for future in futures
            )
            if not active:
                self.logger.warning(
                    "space budget blocks %s: used %.2f GB, peak reserve %.2f GB, limit %s GB",
                    target.name,
                    usage,
                    peak,
                    self.config.max_cache_gb,
                )
                return False
            self.logger.info(
                "waiting for uploads to free space for %s: used %.2f GB, need %.2f GB",
                target.name,
                usage,
                peak,
            )
            self.shutdown_event.wait(5)
        return False

    def _managed_usage_bytes(self) -> int:
        roots = {self.config.sessions_dir, self.config.video_dir.expanduser()}
        total = 0
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _prepare_part(
        self,
        target: TargetConfig,
        session: SessionRecord,
        session_dir: Path,
        source: Path,
        part_index: int,
        *,
        upload_allowed: bool = True,
    ) -> SessionPart | None:
        if target.record_danmaku:
            danmaku_source = self._find_danmaku_source(source)
            if danmaku_source is not None:
                rendered = self._prepare_danmaku_part(
                    target,
                    session,
                    session_dir,
                    source,
                    danmaku_source,
                    part_index,
                    upload_allowed=upload_allowed,
                )
                if rendered is not None:
                    return rendered
        try:
            media = self.media.process_file(source, session_dir, part_index=part_index)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("failed to process segment %s: %s", source, exc)
            return None
        if media is None:
            return None
        source_path = session_dir / media.path
        start_epoch = session.detected_start_epoch or session.created_epoch
        output_dir = session_output_dir(
            self.config.video_dir,
            target.name,
            start_epoch,
            self.config.timezone,
            session.room_title,
            session.session_id,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        started = datetime.fromtimestamp(start_epoch, ZoneInfo(self.config.timezone))
        base_name = f"{started.strftime('%H%M')}_{safe_path_name(session.room_title or '直播录像')}_P{part_index:02d}"
        suffix = Path(source_path.name[:-5]).suffix.lower() if source_path.name.lower().endswith(".part") else source_path.suffix.lower()
        final_media = output_dir / f"{base_name}{suffix}"
        if source_path != final_media:
            shutil.move(str(source_path), str(final_media))
        original_final: Path | None = None
        if media.source:
            original = session_dir / media.source
            if original.exists():
                original_suffix = ".flv" if original.name.lower().endswith(".flv.part") else original.suffix.lower()
                original_final = output_dir / f"{base_name}{original_suffix}"
                shutil.move(str(original), str(original_final))

        danmaku_source = self._find_danmaku_source(source)
        if danmaku_source is None and media.source:
            danmaku_source = self._find_danmaku_source(session_dir / media.source)
        danmaku_final: Path | None = None
        if danmaku_source is not None and danmaku_source.exists():
            danmaku_final = output_dir / f"{base_name}.xml"
            shutil.move(str(danmaku_source), str(danmaku_final))

        part = SessionPart(
            index=part_index,
            status="PENDING",
            path=str(final_media),
            source_path=str(original_final or ""),
            danmaku_path=str(danmaku_final or ""),
            size=final_media.stat().st_size,
            duration_seconds=media.duration_seconds,
        )
        session.parts.append(part)
        if not session.title:
            session.title = build_title(target.title_template, target.name, target.url, session, self.config.timezone)
        part.title = f"{session.title}｜P{part_index:02d}"
        self.store.save(session)


        if not upload_allowed:
            part.status = "LOCAL_ONLY"
            self.store.save(session)
            self.analytics.upsert(session)
        return part

    def _prepare_danmaku_part(
        self,
        target: TargetConfig,
        session: SessionRecord,
        session_dir: Path,
        source: Path,
        danmaku_source: Path,
        part_index: int,
        *,
        upload_allowed: bool,
    ) -> SessionPart | None:
        start_epoch = session.detected_start_epoch or session.created_epoch
        output_dir = session_output_dir(
            self.config.video_dir,
            target.name,
            start_epoch,
            self.config.timezone,
            session.room_title,
            session.session_id,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        started = datetime.fromtimestamp(start_epoch, ZoneInfo(self.config.timezone))
        base_name = f"{started.strftime('%H%M')}_{safe_path_name(session.room_title or '直播录像')}_P{part_index:02d}"
        burned = output_dir / f"{base_name}.mp4"
        try:
            count = self.danmaku.render(
                source,
                danmaku_source,
                burned,
                quality=self.config.quality,
                frame_rate=self.config.frame_rate,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("failed to render danmaku for %s: %s", source, exc)
            burned.unlink(missing_ok=True)
            return None
        if count <= 0:
            return None

        raw_suffix = Path(source.name[:-5]).suffix.lower() if source.name.lower().endswith(".part") else source.suffix.lower()
        raw_final: Path | None = None
        if self.config.keep_original_files:
            raw_final = output_dir / f"{base_name}{raw_suffix}"
            if source != raw_final:
                shutil.move(str(source), str(raw_final))
        else:
            source.unlink(missing_ok=True)

        danmaku_final = output_dir / f"{base_name}.xml"
        shutil.move(str(danmaku_source), str(danmaku_final))
        part = SessionPart(
            index=part_index,
            status="PENDING",
            path=str(burned),
            source_path=str(raw_final or ""),
            danmaku_path=str(danmaku_final),
            size=burned.stat().st_size,
            duration_seconds=self.media.probe_duration(burned),
        )
        session.parts.append(part)
        if not session.title:
            session.title = build_title(target.title_template, target.name, target.url, session, self.config.timezone)
        part.title = f"{session.title}｜P{part_index:02d}"
        self.store.save(session)
        if not upload_allowed:
            part.status = "LOCAL_ONLY"
            self.store.save(session)
            self.analytics.upsert(session)
        return part

    @staticmethod
    def _find_danmaku_source(media_path: Path) -> Path | None:
        candidates = [media_path.with_suffix(".xml"), media_path.parent / f"{media_path.name.removesuffix('.part')}.xml"]
        if media_path.name.endswith(".part"):
            candidates.append(media_path.with_suffix("").with_suffix(".xml"))
        return next((candidate for candidate in candidates if candidate.exists()), None)

    def _upload_part_job(
        self,
        target: TargetConfig,
        session: SessionRecord,
        part: SessionPart,
    ) -> bool:
        final_media = Path(part.path)
        original_final = Path(part.source_path) if part.source_path else None
        result = self._upload_part_with_retries(target, session, final_media, part)
        if result.verified and result.bvid:
            session.bvid = result.bvid
            part.bvid = result.bvid
            part.status = "UPLOADED"
            part.uploaded_at = int(time.time())
            self.store.save(session)
            self.analytics.upsert(session)
            self._bind_collection(target, session)
            if self.config.delete_after_upload:
                danmaku_final = Path(part.danmaku_path) if part.danmaku_path else None
                for path in (final_media, original_final, danmaku_final):
                    if path is not None and path.exists():
                        path.unlink(missing_ok=True)
            return True
        part.status = "UPLOAD_FAILED"
        part.error = "submission was sent but BVID was not verified"
        self.store.save(session)
        self.analytics.upsert(session)
        return False

    def _wait_for_uploads(self, session_id: str, futures: list[Future[bool]]) -> None:
        if futures:
            wait(futures)
        self._pending_uploads.pop(session_id, None)

    def _bind_collection(self, target: TargetConfig, session: SessionRecord) -> None:
        if (
            session.collection_status == "BOUND"
            or not session.bvid
            or (not target.collection_id and not target.collection_name)
        ):
            return
        try:
            manager = BilibiliCollectionManager(self.config.cookie_file)
            collection = None
            if target.collection_id:
                try:
                    collection = manager.find_collection_by_id(int(target.collection_id))
                except (TypeError, ValueError):
                    collection = None
            if collection is None:
                collection = manager.ensure_collection(
                    target.collection_name or target.name,
                    session.bvid,
                )
            manager.add_video(collection, session.bvid, session.title)
            target.collection_id = str(collection.id)
            session.collection_id = str(collection.id)
            session.collection_status = "BOUND"
            self._persist_collection(target)
        except Exception as exc:  # noqa: BLE001
            session.collection_status = "FAILED"
            session.error = f"collection binding failed: {exc}"
            self.logger.warning("collection binding failed for %s: %s", target.name, exc)
        self.store.save(session)
        self.analytics.upsert(session)

    def _persist_collection(self, target: TargetConfig) -> None:
        try:
            store = UIStateStore(self.config)
            state = store.load()
            changed = False
            for item in state.get("targets", []):
                if item.get("name") != target.name:
                    continue
                item["collection_id"] = target.collection_id
                item["collection_name"] = target.collection_name or target.name
                changed = True
                break
            if changed:
                store.save(state)
                store.render_runtime_config(state)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("failed to persist collection id for %s: %s", target.name, exc)

    def _upload_part_with_retries(
        self,
        target: TargetConfig,
        session: SessionRecord,
        media_path: Path,
        part: SessionPart,
    ) -> UploadResult:
        for attempt in range(self.config.upload_retry_count + 1):
            try:
                part.status = "UPLOADING"
                self.store.save(session)
                result = self.uploader.upload_part(
                    target,
                    session,
                    media_path,
                    part_index=part.index,
                    title=part.title,
                    bvid=session.bvid,
                )
                if result.verified:
                    return result
                if attempt < self.config.upload_retry_count:
                    self.shutdown_event.wait(self.config.upload_retry_backoff_seconds * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                part.error = str(exc)
                self.logger.exception("part upload failed for %s", part.index)
                if attempt < self.config.upload_retry_count:
                    self.shutdown_event.wait(self.config.upload_retry_backoff_seconds * (attempt + 1))
        return UploadResult(None, False, [])

    def _wait_for_reconnect(self, target: TargetConfig, session: SessionRecord) -> bool:
        grace = self.config.reconnect_grace_minutes * 60
        if grace <= 0:
            return False
        started = int(time.time())
        while not self.shutdown_event.is_set() and not self.interrupt_event.is_set():
            status = self._resolve_status(target)
            if status is not None and status.live:
                session.reconnect_count += 1
                session.reconnect_seconds += max(0, int(time.time()) - started)
                session.last_seen_live_epoch = int(time.time())
                self.store.save(session)
                self.analytics.upsert(session)
                return True
            elapsed = int(time.time()) - started
            if elapsed > grace:
                return False
            self.shutdown_event.wait(min(30, max(1, grace - elapsed)))
        return False

    def _apply_schedule(self, target: TargetConfig, session: SessionRecord, detected_epoch: int) -> None:
        if not target.schedule:
            return
        moment = datetime.fromtimestamp(detected_epoch, ZoneInfo(self.config.timezone))
        slot = active_slot(target.schedule, moment)
        if slot is None:
            slot = target.schedule[0]
        expected = expected_start_for_moment(slot, moment)
        session.scheduled_start_epoch = int(expected.timestamp())
        late, minutes = is_late_detection(moment, expected, self.config.late_threshold_minutes)
        session.late = late
        session.late_minutes = minutes

    def _resolve_status(self, target: TargetConfig):
        try:
            return self.resolver.resolve(target.url)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("failed to resolve target %s: %s", target.name, exc)
            return None

    def _reload_runtime_settings(self, target: TargetConfig) -> None:
        try:
            current = load_config(self.config.config_path)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("failed to reload runtime settings: %s", exc)
            return
        for field in (
            "poll_interval_seconds",
            "max_reconnect_attempts",
            "reconnect_backoff_seconds",
            "segment_time",
            "quality",
            "frame_rate",
            "min_file_size_mb",
            "max_cache_gb",
            "keep_original_files",
            "video_dir",
            "late_threshold_minutes",
            "reconnect_grace_minutes",
            "biliup_bin",
            "ffmpeg_bin",
            "ffprobe_bin",
            "cookie_file",
            "upload_line",
            "public",
            "delete_after_upload",
            "upload_retry_count",
            "upload_retry_backoff_seconds",
            "targets",
        ):
            setattr(self.config, field, getattr(current, field))
        fresh_target = self._target_by_name(target.name)
        if fresh_target is not None:
            for field in (
                "url",
                "enabled",
                "public",
                "record_mode",
                "record_danmaku",
                "watch_mode",
                "collection_name",
                "collection_id",
                "title_template",
                "tags",
                "tid",
                "copyright",
                "source",
                "schedule",
            ):
                setattr(target, field, getattr(fresh_target, field))

    def _is_live(self, target: TargetConfig) -> bool:
        status = self._resolve_status(target)
        if status is not None and status.live:
            return True
        # Douyin's room API intermittently reports live rooms as offline. When a
        # room was resolved, let stream-gears make the final call instead of
        # skipping a running broadcast.
        if status is not None and status.web_rid:
            self.logger.info("resolver reported offline for %s; probing stream", target.name)
        return self._probe_live_with_recorder(target)

    def _probe_live_with_recorder(self, target: TargetConfig) -> bool:
        probe_dir = self.config.data_dir / "probes" / f"{int(time.time() * 1000)}"
        probe_dir.mkdir(parents=True, exist_ok=True)
        try:
            attempt = self.recorder.record(
                target,
                probe_dir,
                timeout_seconds=8,
                allow_partials=True,
            )
            return bool(attempt.media_paths)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("live probe failed for %s: %s", target.name, exc)
            return False
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)

    def _upload_with_retries(self, session: SessionRecord) -> None:
        target = self._target_by_name(session.target_name)
        if target is None:
            session.status = SessionStatus.FAILED
            session.error = f"target no longer exists: {session.target_name}"
            self.store.save(session)
            return
        session_dir = self.config.sessions_dir / session.session_id
        resolved_title = session.title or build_title(
            target.title_template,
            target.name,
            target.url,
            session,
            self.config.timezone,
        )
        session.title = resolved_title
        self.store.save(session)
        if session.parts:
            for part in session.parts:
                if part.status == "UPLOADED":
                    continue
                if not part.title:
                    part.title = f"{resolved_title}｜P{part.index:02d}"
                media_path = Path(part.path)
                if not media_path.exists():
                    part.status = "UPLOAD_FAILED"
                    part.error = f"local media missing: {media_path}"
                    continue
                result = self._upload_part_with_retries(target, session, media_path, part)
                if result.verified and result.bvid:
                    session.bvid = result.bvid
                    part.bvid = result.bvid
                    part.status = "UPLOADED"
                    part.uploaded_at = int(time.time())
            session.status = (
                SessionStatus.UPLOADED
                if session.parts and all(part.status == "UPLOADED" for part in session.parts)
                else SessionStatus.UPLOAD_FAILED
            )
            self.store.save(session)
            self._bind_collection(target, session)
            self.analytics.upsert(session)
            return
        result = self.uploader.upload_session(target, session, session_dir, title=resolved_title)
        session.bvid = result.bvid
        session.status = SessionStatus.UPLOADED if result.verified else SessionStatus.UPLOAD_SUBMITTED_UNVERIFIED
        session.error = "" if result.verified else "submission was sent but BVID was not verified"
        self.store.save(session)
        self.analytics.upsert(session)

    def _new_session(self, target: TargetConfig) -> SessionRecord:
        now = datetime.now(ZoneInfo(self.config.timezone))
        target_hash = hashlib.sha1(target.name.encode("utf-8")).hexdigest()[:6]
        session_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{slugify(target.name)}-{target_hash}"
        return SessionRecord(
            session_id=session_id,
            target_name=target.name,
            target_url=target.url,
            created_epoch=int(now.timestamp()),
            detected_start_epoch=None,
            detected_start_iso=None,
            title="",
            record_mode=target.record_mode,
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
        self.request_pause("upload")

    def request_pause(self, mode: str) -> None:
        with self._state_lock:
            self._pause_mode = mode
        self.interrupt_event.set()
        self.record_runner.terminate_active()

    def _wait_for_stop(self, seconds: int) -> bool:
        deadline = time.monotonic() + max(0, seconds)
        while not self.shutdown_event.is_set():
            if self.interrupt_event.is_set():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.shutdown_event.wait(min(1, remaining))
        return True

    def _manual_request_path(self, target: TargetConfig) -> Path:
        return self.config.data_dir / "ui" / "manual" / f"{target_key(target.name)}.request"

    def _consume_manual_request(self, target: TargetConfig) -> bool:
        path = self._manual_request_path(target)
        if not path.exists():
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        self.logger.info("manual check requested for %s", target.name)
        return True

    def pause_mode(self) -> str:
        with self._state_lock:
            return self._pause_mode

    def _start_external_stop_watcher(self) -> None:
        stop_path = os.environ.get("DOUYIN_RECORDER_STOP_FILE", "").strip()
        if not stop_path:
            return

        def watch() -> None:
            while not self.shutdown_event.wait(2):
                if os.path.exists(stop_path):
                    try:
                        mode = Path(stop_path).read_text(encoding="utf-8").strip() or "upload"
                    except OSError:
                        mode = "upload"
                    self.logger.info("external pause request received: %s", mode)
                    self.request_pause(mode)
                    return

        threading.Thread(target=watch, name="external-stop-watcher", daemon=True).start()
