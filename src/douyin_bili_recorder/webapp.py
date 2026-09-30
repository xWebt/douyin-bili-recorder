from __future__ import annotations

import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import subprocess
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import BilibiliAuth
from .analytics import AnalyticsStore
from .config import AppConfig
from .config import resolve_executable
from .douyin import DouyinResolver
from .paths import anchor_dir, session_output_dir, target_key
from .service_control import ServiceController
from .ui_state import UIStateStore
from .bilibili_status import BilibiliSubmissionClient
from .reports import ReportGenerator
from .state import SessionStore
from .models import SessionStatus
from .upload_progress import UploadProgressStore

WEB_ROOT = Path(__file__).with_name("web")


def _delete_managed_file(path: Path, roots: list[Path]) -> int:
    try:
        resolved = path.expanduser().resolve()
        if not any(resolved == root or root in resolved.parents for root in roots):
            return 0
        size = resolved.stat().st_size
        resolved.unlink(missing_ok=True)
        return size
    except OSError:
        return 0


def _clear_target_cache(config: AppConfig, target_name: str) -> dict[str, Any]:
    sessions = [
        session
        for session in SessionStore(config.sessions_dir).all()
        if session.target_name == target_name
    ]
    state = UIStateStore(config).load()
    target_state = next(
        (item for item in state.get("targets", []) if item.get("name") == target_name),
        None,
    )
    cloud_backup = bool(target_state.get("cloud_backup", False) if target_state else False) or any(
        session.cloud_backup for session in sessions
    )
    roots = [config.sessions_dir.resolve(), config.video_dir.expanduser().resolve()]
    progress_store = UploadProgressStore(config.data_dir)
    safe_statuses = {"UPLOADED", "CANCELED", "DISCARDED"}
    deleted_files = 0
    freed_bytes = 0
    skipped_active_sessions = 0
    skipped_cloud_pending = 0

    for session in sessions:
        if session.status in {SessionStatus.RECORDING, SessionStatus.STARTING}:
            skipped_active_sessions += 1
            continue
        if not session.parts:
            continue
        for part in session.parts:
            if part.status not in safe_statuses:
                continue
            if cloud_backup and part.cloud_status != "UPLOADED":
                skipped_cloud_pending += 1
                continue
            for value in (part.path, part.source_path, part.danmaku_path):
                if not value:
                    continue
                freed = _delete_managed_file(Path(value), roots)
                if freed:
                    deleted_files += 1
                    freed_bytes += freed
            progress_store.remove(f"{session.session_id}:{part.index}")
        if cloud_backup and any(
            part.status in safe_statuses and part.cloud_status != "UPLOADED"
            for part in session.parts
        ):
            continue
        if all(part.status in safe_statuses for part in session.parts):
            session_dir = config.sessions_dir / session.session_id
            if session_dir.exists():
                for child in list(session_dir.iterdir()):
                    if child.name == "session.json":
                        continue
                    try:
                        if child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                        else:
                            child.unlink(missing_ok=True)
                    except OSError:
                        continue
    return {
        "ok": True,
        "target": target_name,
        "deleted_files": deleted_files,
        "freed_bytes": freed_bytes,
        "skipped_active_sessions": skipped_active_sessions,
        "skipped_cloud_pending": skipped_cloud_pending,
    }


def _test_cloud_remote(config: AppConfig, remote: str) -> dict[str, Any]:
    value = remote.strip().rstrip("/")
    if not value or ":" not in value:
        raise HTTPException(status_code=400, detail="远端路径需使用 rclone 格式，例如 openlist:/DouyinBiliRecorder")
    state = UIStateStore(config).load()
    rclone_bin = resolve_executable(
        str(state.get("cloud_rclone_bin", config.cloud_rclone_bin)),
        config.config_path.parent,
    )
    try:
        result = subprocess.run(
            [rclone_bin, "lsf", value, "--max-depth", "1"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"rclone 不存在：{rclone_bin}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="网盘远端测试超时") from exc
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        raise HTTPException(status_code=422, detail=output or f"rclone exited with {result.returncode}")
    return {"ok": True, "remote": value, "message": output or "远端可访问"}


def _request_upload_control(
    config: AppConfig,
    session_id: str,
    part_index: int,
    action: str,
) -> dict[str, Any]:
    session_store = SessionStore(config.sessions_dir)
    try:
        session = session_store.load(session_id)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    part = next((item for item in session.parts if item.index == part_index), None)
    if part is None:
        raise HTTPException(status_code=404, detail="part not found")
    if part.status == "UPLOADED":
        raise HTTPException(status_code=409, detail="part already uploaded")
    if action == "retry":
        if not part.path or not Path(part.path).exists():
            raise HTTPException(status_code=409, detail="本地视频文件不存在，无法重试")
        part.status = "PENDING"
        part.error = ""
        progress_message = "等待重试"
        progress_state = "queued"
    elif action == "pause":
        part.status = "PAUSED"
        part.error = "上传已暂停"
        progress_message = "已暂停"
        progress_state = "paused"
    else:
        part.status = "CANCELED"
        part.error = "上传已由用户停止"
        progress_message = "已停止"
        progress_state = "stopped"
    session_store.save(session)
    control_dir = config.data_dir / "ui" / "upload-control"
    control_dir.mkdir(parents=True, exist_ok=True)
    request_path = control_dir / f"{session_id}-{part_index}.request"
    request_path.write_text(
        json.dumps(
            {"session_id": session_id, "part_index": part_index, "action": action},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    existing = next(
        (item for item in UploadProgressStore(config.data_dir).load_all() if item.get("key") == f"{session_id}:{part_index}"),
        {},
    )
    payload = dict(existing)
    payload.update(
        {
            "available": True,
            "message": progress_message,
            "state": progress_state,
            "target": session.target_name,
            "part": part_index,
            "title": part.title or session.title,
            "path": part.path,
            "total_bytes": part.size,
            "uploaded_bytes": payload.get("uploaded_bytes", 0),
            "percent": 0 if action == "retry" else payload.get("percent", 0),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    UploadProgressStore(config.data_dir).upsert(f"{session_id}:{part_index}", payload)
    return {"ok": True, "session_id": session_id, "part_index": part_index, "action": action}



def _ensure_service_running(config: AppConfig, state_store: UIStateStore, controller: ServiceController) -> None:
    state = state_store.load()
    limit = int(state.get("max_cache_gb", config.max_cache_gb))
    if not controller.status(limit).get("running"):
        controller.start()



def _start_target(
    config: AppConfig,
    state_store: UIStateStore,
    controller: ServiceController,
    target_name: str,
) -> dict[str, Any]:
    state = state_store.load()
    target = next((item for item in state.get("targets", []) if item.get("name") == target_name), None)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    target["enabled"] = True
    state_store.save(state)
    state_store.render_runtime_config(state)
    request_path = config.data_dir / "ui" / "manual" / f"{target_key(target_name)}.request"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("1", encoding="utf-8")
    _ensure_service_running(config, state_store, controller)
    return {"ok": True, "target": target_name, "enabled": True}


def _pause_target(
    config: AppConfig,
    state_store: UIStateStore,
    controller: ServiceController,
    target_name: str,
) -> dict[str, Any]:
    state = state_store.load()
    target = next((item for item in state.get("targets", []) if item.get("name") == target_name), None)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    target["enabled"] = False
    state_store.save(state)
    state_store.render_runtime_config(state)
    request_dir = config.data_dir / "ui" / "target-control"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{target_key(target_name)}.request"
    request_path.write_text(
        json.dumps({"name": target_name, "action": "pause"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"ok": True, "target": target_name, "enabled": False}


def create_app(config: AppConfig) -> FastAPI:
    state_store = UIStateStore(config)
    auth = BilibiliAuth(config.cookie_file)
    controller = ServiceController(config, state_store)
    analytics = AnalyticsStore(config.video_dir, config.timezone)
    resolver = DouyinResolver()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        controller.start_supervisor()
        try:
            yield
        finally:
            controller.stop_supervisor()
            controller.stop("keep")

    app = FastAPI(title="Douyin recorder control deck", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        ui_state = state_store.load()
        state_store.render_runtime_config(ui_state)
        return {
            "authenticated": config.cookie_file.exists(),
            "config": ui_state,
            "service": controller.status(int(ui_state.get("max_cache_gb", config.max_cache_gb))),
            "config_path": str(config.config_path),
        }

    @app.put("/api/state")
    async def put_state(payload: dict[str, Any]) -> dict[str, Any]:
        state = state_store.save(payload)
        state_store.render_runtime_config(state)
        return {"config": state, "restart_required": True}

    @app.post("/api/service/{action}")
    async def service_action(action: str, mode: str = "upload") -> dict[str, Any]:
        if action == "start":
            return controller.start()
        if action == "stop":
            return controller.stop(mode)
        if action == "restart":
            return controller.restart(mode)
        raise HTTPException(status_code=404, detail="unknown service action")

    @app.post("/api/auth/qrcode")
    async def auth_qrcode() -> dict[str, Any]:
        return auth.begin()

    @app.get("/api/auth/poll")
    async def auth_poll(session_id: str) -> dict[str, str]:
        return auth.poll(session_id)

    @app.get("/api/logs")
    async def logs(lines: int = 160) -> dict[str, Any]:
        limit = max(10, min(lines, 1000))
        recorder_log = config.logs_dir / "recorder.log"
        paths = [recorder_log] if recorder_log.exists() else [state_store.worker_log_path]
        return {"lines": _tail_logs(paths, limit)}

    @app.post("/api/targets/resolve")
    async def resolve_target(payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url", "")).strip()
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        try:
            return resolver.resolve(url, check_live=bool(payload.get("check_live", True))).to_dict()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/targets/{target_name}/analytics")
    async def target_analytics(target_name: str, month: str | None = None) -> dict[str, Any]:
        selected_month = month or datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m")
        return analytics.summary(target_name, selected_month)

    @app.get("/api/targets/{target_name}/reports/{period}")
    async def target_report(
        target_name: str,
        period: str,
        anchor_date: str | None = None,
        allow_partial: bool = False,
    ) -> FileResponse:
        if period not in {"week", "month"}:
            raise HTTPException(status_code=400, detail="period must be week or month")
        selected_date = None
        if anchor_date:
            try:
                selected_date = date.fromisoformat(anchor_date)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="anchor_date must be YYYY-MM-DD") from exc
        try:
            report = ReportGenerator(config.video_dir.expanduser(), config.timezone)
            _start, end, _label, _filename = report.period_bounds(period, selected_date, target_name)
            today = datetime.now(ZoneInfo(config.timezone)).date()
            effective_end = None
            if end >= today:
                if not allow_partial or period != "week":
                    raise HTTPException(status_code=409, detail="当前周期尚未结束，请生成上一个完整周期")
                effective_end = today
            path = report.generate(
                target_name,
                period,
                anchor_date=selected_date,
                end_date=effective_end,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"report generation failed: {exc}") from exc
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @app.post("/api/uploads/{session_id}/{part_index}/stop")
    async def stop_upload(session_id: str, part_index: int) -> dict[str, Any]:
        return _request_upload_control(config, session_id, part_index, "stop")

    @app.post("/api/uploads/{session_id}/{part_index}/pause")
    async def pause_upload(session_id: str, part_index: int) -> dict[str, Any]:
        return _request_upload_control(config, session_id, part_index, "pause")

    @app.post("/api/uploads/{session_id}/{part_index}/retry")
    async def retry_upload(session_id: str, part_index: int) -> dict[str, Any]:
        result = _request_upload_control(config, session_id, part_index, "retry")
        _ensure_service_running(config, state_store, controller)
        return result

    @app.post("/api/targets/{target_name}/clear-cache")
    async def clear_target_cache(target_name: str) -> dict[str, Any]:
        state = state_store.load()
        known = {str(item.get("name", "")) for item in state.get("targets", [])}
        if target_name not in known:
            raise HTTPException(status_code=404, detail="target not found")
        return _clear_target_cache(config, target_name)

    @app.post("/api/cloud/test")
    async def test_cloud_remote(payload: dict[str, Any]) -> dict[str, Any]:
        remote = str(payload.get("remote", "")).strip()
        return _test_cloud_remote(config, remote)

    @app.get("/api/bilibili/submissions")
    async def bilibili_submissions() -> dict[str, Any]:
        sessions = SessionStore(config.sessions_dir).all()
        metadata: dict[str, list[dict[str, Any]]] = {}
        for session in sessions:
            bvids = {session.bvid} if session.bvid else set()
            bvids.update(part.bvid for part in session.parts if part.bvid)
            for bvid in bvids:
                metadata.setdefault(str(bvid), []).append(
                    {
                        "target": session.target_name,
                        "session_id": session.session_id,
                        "title": session.title,
                        "parts": len(session.parts),
                    }
                )
        if not metadata:
            return {"available": True, "submissions": [], "message": "暂无已投稿稿件"}
        try:
            statuses = BilibiliSubmissionClient(config.cookie_file).list_for_bvids(set(metadata))
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "submissions": [], "message": str(exc)}

        submissions = []
        for status in statuses:
            item = status.to_dict()
            matches = metadata.get(status.bvid, [])
            item["targets"] = sorted({str(match.get("target") or "") for match in matches})
            item["session_title"] = matches[-1].get("title") if matches else item.get("title")
            submissions.append(item)
        submissions.sort(key=lambda item: (item.get("created_epoch", 0), item.get("bvid", "")), reverse=True)
        return {"available": True, "submissions": submissions, "message": ""}

    @app.post("/api/targets/{target_name}/manual-start")
    async def manual_start_target(target_name: str) -> dict[str, Any]:
        return _start_target(config, state_store, controller, target_name)

    @app.post("/api/targets/{target_name}/pause")
    async def pause_target(target_name: str) -> dict[str, Any]:
        return _pause_target(config, state_store, controller, target_name)

    @app.get("/api/videos")
    async def video_library() -> dict[str, Any]:
        root = config.video_dir.expanduser()
        anchors = []
        if root.exists():
            for path in sorted(root.iterdir(), key=lambda item: item.name):
                if not path.is_dir():
                    continue
                anchors.append({"name": path.name, "path": str(path)})
        return {"root": str(root), "anchors": anchors}

    @app.post("/api/open-folder")
    async def open_folder(payload: dict[str, Any]) -> dict[str, str]:
        kind = str(payload.get("kind", "root"))
        name = str(payload.get("name", ""))
        session_id = str(payload.get("session_id", ""))
        if kind == "root":
            path = config.video_dir.expanduser()
        elif kind == "anchor":
            path = anchor_dir(config.video_dir.expanduser(), name)
        elif kind == "session":
            target = next((item for item in config.targets if item.name == name), None)
            record = next((item for item in ServiceController(config, state_store).status().get("sessions", []) if item.get("session_id") == session_id), None)
            if target is None or record is None or not record.get("started_at"):
                raise HTTPException(status_code=404, detail="session not found")
            try:
                start_epoch = int(datetime.fromisoformat(str(record["started_at"]).replace("Z", "+00:00")).timestamp())
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid session start time") from exc
            path = session_output_dir(
                config.video_dir.expanduser(),
                target.name,
                start_epoch,
                config.timezone,
                str(record.get("title") or ""),
                session_id,
            )
        else:
            raise HTTPException(status_code=400, detail="unknown folder kind")
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["open", str(path)], start_new_session=True)
        return {"path": str(path)}

    return app


def _tail_logs(paths: list[Path], limit: int) -> list[str]:
    combined: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        combined.extend(content[-limit:])
    return combined[-limit:]
