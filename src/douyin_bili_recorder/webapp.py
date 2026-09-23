from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import BilibiliAuth
from .config import AppConfig
from .service_control import ServiceController
from .ui_state import UIStateStore

WEB_ROOT = Path(__file__).with_name("web")


def create_app(config: AppConfig) -> FastAPI:
    state_store = UIStateStore(config)
    auth = BilibiliAuth(config.cookie_file)
    controller = ServiceController(config, state_store)

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
            "service": controller.status(),
            "config_path": str(config.config_path),
        }

    @app.put("/api/state")
    async def put_state(payload: dict[str, Any]) -> dict[str, Any]:
        state = state_store.save(payload)
        state_store.render_runtime_config(state)
        return {"config": state, "restart_required": True}

    @app.post("/api/service/{action}")
    async def service_action(action: str) -> dict[str, Any]:
        if action == "start":
            return controller.start()
        if action == "stop":
            return controller.stop()
        if action == "restart":
            return controller.restart()
        raise HTTPException(status_code=404, detail="unknown service action")

    @app.post("/api/auth/qrcode")
    async def auth_qrcode() -> dict[str, str]:
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
