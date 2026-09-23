from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import uvicorn
import webview

from .config import AppConfig
from .webapp import create_app


def run_desktop(config: AppConfig, *, debug: bool = False) -> None:
    port = _free_port()
    app = create_app(config)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, name="control-deck-server", daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("control deck server failed to start")

    webview.create_window(
        "抖音直播录制器",
        f"http://127.0.0.1:{port}/",
        width=1440,
        height=920,
        min_size=(980, 680),
        background_color="#0e1412",
        text_select=True,
    )
    try:
        webview.start(debug=debug)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
