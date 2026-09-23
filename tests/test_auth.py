from __future__ import annotations

from pathlib import Path

import requests

from douyin_bili_recorder import auth as auth_module
from douyin_bili_recorder.auth import BilibiliAuth


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, *, error: Exception | None = None, payload=None):
        self.error = error
        self.payload = payload
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return FakeResponse(self.payload)


def test_auth_uses_direct_connection_first(monkeypatch, tmp_path: Path) -> None:
    auth = BilibiliAuth(tmp_path / "cookies.json")
    direct = FakeSession(payload={"code": 0})
    auth.session = direct
    monkeypatch.setattr(auth_module, "detect_system_proxy", lambda: "http://127.0.0.1:7897")

    response = auth._post("https://example.com", timeout=1)

    assert response.json() == {"code": 0}
    assert direct.calls == 1
    assert auth.proxy_session is None


def test_auth_falls_back_to_system_proxy(monkeypatch, tmp_path: Path) -> None:
    auth = BilibiliAuth(tmp_path / "cookies.json")
    auth.session = FakeSession(error=requests.ConnectionError("direct failed"))
    auth.proxy_session = FakeSession(payload={"code": 0})
    monkeypatch.setattr(auth_module, "detect_system_proxy", lambda: "http://127.0.0.1:7897")

    response = auth._post("https://example.com", timeout=1)

    assert response.json() == {"code": 0}
    assert auth.session.calls == 1
    assert auth.proxy_session.calls == 1
