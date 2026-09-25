from __future__ import annotations

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
from .douyin import DouyinResolver
from .paths import anchor_dir, session_output_dir, target_key
from .service_control import ServiceController
from .ui_state import UIStateStore
from .bilibili_status import BilibiliSubmissionClient
from .reports import ReportGenerator
from .state import SessionStore

WEB_ROOT = Path(__file__).with_name("web")


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
        state = state_store.load()
        target = next((item for item in state.get("targets", []) if item.get("name") == target_name), None)
        if target is None:
            raise HTTPException(status_code=404, detail="target not found")
        status = controller.status(int(state.get("max_cache_gb", config.max_cache_gb)))
        if not status.get("running"):
            controller.start()
        request_path = config.data_dir / "ui" / "manual" / f"{target_key(target_name)}.request"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text("1", encoding="utf-8")
        return {"ok": True, "target": target_name}

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
