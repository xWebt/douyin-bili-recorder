from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import SessionRecord
from .state import SessionStore
from .storage_guard import StorageGuard
from .ui_state import UIStateStore


class ServiceController:
    def __init__(self, config: AppConfig, state_store: UIStateStore) -> None:
        self.config = config
        self.store = state_store
        self._stop_event = threading.Event()
        self._supervisor: threading.Thread | None = None
        self.stop_request_path = self.store.root / "stop.request"

    def start(self) -> dict[str, Any]:
        self.stop_request_path.unlink(missing_ok=True)
        state = self.store.load()
        self.config.max_cache_gb = max(1, int(state.get("max_cache_gb", self.config.max_cache_gb)))
        self.config.delete_after_upload = bool(
            state.get("delete_after_upload", self.config.delete_after_upload)
        )
        self.config.public = bool(state.get("public", self.config.public))
        state["worker_running"] = True
        state = self.store.save(state)
        config_path = self.store.render_runtime_config(state)
        runtime = self.store.load_runtime_state()
        pid = int(runtime.get("pid", 0) or 0)
        if pid and self._pid_alive(pid):
            return self.status()

        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["DOUYIN_RECORDER_STOP_FILE"] = str(self.stop_request_path)
        environment["PATH"] = os.pathsep.join(
            [
                str(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "bin"),
                str(Path(sys.executable).parent),
                str(self.config.config_path.parent / ".tools" / "ffmpeg"),
                environment.get("PATH", ""),
            ]
        )
        log_handle = self.store.worker_log_path.open("a", encoding="utf-8")
        if getattr(sys, "frozen", False):
            command = [
                sys.executable,
                "--internal-recorder",
                "run",
                "--config",
                str(config_path),
            ]
        else:
            command = [
                sys.executable,
                "-m",
                "douyin_bili_recorder",
                "run",
                "--config",
                str(config_path),
            ]
        process = subprocess.Popen(
            command,
            cwd=str(self.config.config_path.parent),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=environment,
            close_fds=True,
        )
        self.store.save_runtime_state(
            {
                "pid": process.pid,
                "started_at": int(time.time()),
                "config_path": str(config_path),
                "mode": "detached-supervisor",
            }
        )
        return self.status()

    def stop(self, mode: str = "upload") -> dict[str, Any]:
        state = self.store.load()
        state["worker_running"] = False
        self.store.save(state)
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.stop_request_path.write_text(mode if mode in {"upload", "keep"} else "upload", encoding="utf-8")
        runtime = self.store.load_runtime_state()
        pid = int(runtime.get("pid", 0) or 0)
        if pid and self._pid_alive(pid):
            if mode == "upload":
                try:
                    os.killpg(pid, signal.SIGINT)
                except (PermissionError, ProcessLookupError):
                    pass
                return self.status()
            self._terminate(pid)
            self.store.save_runtime_state({})
        return self.status()

    def restart(self, mode: str = "upload") -> dict[str, Any]:
        self.stop(mode)
        time.sleep(0.5)
        return self.start()

    def status(self, cache_limit_gb: int | None = None) -> dict[str, Any]:
        runtime = self.store.load_runtime_state()
        pid = int(runtime.get("pid", 0) or 0)
        alive = bool(pid and self._pid_alive(pid))
        started_at = int(runtime.get("started_at", 0) or 0)
        sessions = self._sessions()
        storage = StorageGuard(self.config.sessions_dir, logging.getLogger(self.config.name))
        cache_used_gb = storage.usage_gb()
        if cache_limit_gb is None:
            try:
                cache_limit_gb = int(self.store.load().get("max_cache_gb", self.config.max_cache_gb))
            except (TypeError, ValueError):
                cache_limit_gb = self.config.max_cache_gb
        saved_cache_limit = int(cache_limit_gb or self.config.max_cache_gb)
        return {
            "cache_used_gb": cache_used_gb,
            "cache_limit_gb": saved_cache_limit,
            "active_cache_limit_gb": self.config.max_cache_gb,
            "cache_used_percent": round(cache_used_gb / saved_cache_limit * 100, 1) if saved_cache_limit else 0,
            "running": alive,
            "pid": pid if alive else None,
            "started_at": started_at if alive else None,
            "uptime_seconds": int(time.time()) - started_at if alive and started_at else 0,
            "mode": runtime.get("mode") if alive else None,
            "desired_running": bool(self.store.load().get("worker_running", False)),
            "disk_free_gb": round(self._disk_free() / (1024**3), 2),
            "sessions": [self._session_dict(item) for item in sessions[:20]],
        }

    def start_supervisor(self) -> None:
        if self._supervisor and self._supervisor.is_alive():
            return
        self._stop_event.clear()
        self._supervisor = threading.Thread(target=self._supervise, name="service-supervisor", daemon=True)
        self._supervisor.start()

    def stop_supervisor(self) -> None:
        self._stop_event.set()
        if self._supervisor:
            self._supervisor.join(timeout=2)

    def _supervise(self) -> None:
        while not self._stop_event.wait(4):
            state = self.store.load()
            if not state.get("auto_restart", True) or not state.get("worker_running", False):
                continue
            runtime = self.store.load_runtime_state()
            pid = int(runtime.get("pid", 0) or 0)
            if not pid or not self._pid_alive(pid):
                try:
                    self.start()
                except Exception:
                    continue

    def _sessions(self) -> list[SessionRecord]:
        return sorted(
            SessionStore(self.config.sessions_dir).all(),
            key=lambda item: item.created_epoch,
            reverse=True,
        )

    def _session_dict(self, session: SessionRecord) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "target_name": session.target_name,
            "status": session.status,
            "started_at": session.detected_start_iso,
            "title": session.title,
            "bvid": session.bvid,
            "parts": len(session.parts),
            "collection_status": session.collection_status,
            "error": session.error,
        }

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _terminate(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGINT)
        except PermissionError:
            pass
        except ProcessLookupError:
            return
        deadline = time.time() + 8
        while time.time() < deadline and self._pid_alive(pid):
            time.sleep(0.2)
        if self._pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except PermissionError:
                pass
            except ProcessLookupError:
                pass

    def _disk_free(self) -> int:
        path = self.config.data_dir
        path.mkdir(parents=True, exist_ok=True)
        return os.statvfs(path).f_bavail * os.statvfs(path).f_frsize
