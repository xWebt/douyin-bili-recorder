from __future__ import annotations

import base64
import hashlib
import io
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import qrcode
import requests
from .network import session_proxies

APP_KEY = "4409e2ce8ffd12b8"
APP_SECRET = "59b43e04ad6965f34319062b478f83dd"


@dataclass(slots=True)
class QRSession:
    session_id: str
    auth_code: str
    url: str
    image_base64: str
    created_at: int
    state: str = "waiting"


class BilibiliAuth:
    def __init__(self, cookie_file: Path) -> None:
        self.cookie_file = cookie_file
        self.session = requests.Session()
        self.session.trust_env = True
        self.session.proxies.update(session_proxies())
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/142.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self.sessions: dict[str, QRSession] = {}

    def begin(self) -> dict[str, Any]:
        params = {"appkey": APP_KEY, "local_id": "0", "ts": int(time.time())}
        params["sign"] = hashlib.md5((urlencode(params) + APP_SECRET).encode()).hexdigest()
        response = self.session.post(
            "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code",
            data=params,
            timeout=15,
        ).json()
        if not response or response.get("code") != 0:
            raise RuntimeError("failed to create Bilibili login QR code")
        data = response["data"]
        session_id = uuid.uuid4().hex
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(data["url"])
        qr.make(fit=True)
        image = qr.make_image(fill_color="#111713", back_color="#f4f6f0")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        session = QRSession(
            session_id=session_id,
            auth_code=data["auth_code"],
            url=data["url"],
            image_base64=encoded,
            created_at=int(time.time()),
        )
        self.sessions[session_id] = session
        return {
            "session_id": session_id,
            "image_base64": encoded,
            "expires_in": 180,
        }

    def poll(self, session_id: str) -> dict[str, str]:
        session = self.sessions.get(session_id)
        if session is None:
            return {"state": "missing", "message": "二维码会话已失效"}
        if time.time() - session.created_at > 180:
            session.state = "expired"
            return {"state": "expired", "message": "二维码已过期"}

        params = {
            "appkey": APP_KEY,
            "auth_code": session.auth_code,
            "local_id": "0",
            "ts": int(time.time()),
        }
        params["sign"] = hashlib.md5((urlencode(params) + APP_SECRET).encode()).hexdigest()
        response = self.session.post(
            "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll",
            data=params,
            timeout=10,
        ).json()
        code = response.get("code")
        if code == 0:
            payload = response.get("data") or {}
            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            self.cookie_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            session.state = "authenticated"
            return {"state": "authenticated", "message": "登录成功"}
        if code == 86038:
            session.state = "expired"
            return {"state": "expired", "message": "二维码已过期"}
        if code == 86090:
            session.state = "confirming"
            return {"state": "confirming", "message": "已扫码，请在手机上确认"}
        if code == 86101:
            session.state = "waiting"
            return {"state": "waiting", "message": "等待扫码"}
        return {"state": "waiting", "message": str(response.get("message") or "等待扫码")}
