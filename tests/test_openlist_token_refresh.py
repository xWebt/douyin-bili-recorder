from __future__ import annotations

import threading
from pathlib import Path

import pytest

from douyin_bili_recorder.openlist_api import OpenListApiClient, OpenListApiError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def _client() -> OpenListApiClient:
    return OpenListApiClient(
        base_url="http://127.0.0.1:5244",
        username="admin",
        password="secret",
        remote_name="quark",
        timeout_seconds=60,
    )


def test_json_token_expired_triggers_one_relogin(tmp_path: Path, monkeypatch) -> None:
    client = _client()
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    responses = [
        FakeResponse(200, {"code": 401, "message": "token is expired"}),
        FakeResponse(200, {"code": 200}),
    ]
    logins: list[str] = []

    def login() -> str:
        logins.append("login")
        return f"token-{len(logins)}"

    def put(_path, _api_path, token, _cancel) -> FakeResponse:
        assert token == f"token-{len(logins)}"
        return responses.pop(0)

    monkeypatch.setattr(client, "_login", login)
    monkeypatch.setattr(client, "_put_file", put)

    client.upload(media, "quark:/DouyinBiliRecorder/a.mp4", threading.Event())

    assert len(logins) == 2
    assert responses == []


def test_persistent_token_expiry_raises(tmp_path: Path, monkeypatch) -> None:
    client = _client()
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    responses = [
        FakeResponse(200, {"code": 401, "message": "token is expired"}),
        FakeResponse(200, {"code": 401, "message": "token is expired"}),
    ]
    monkeypatch.setattr(client, "_login", lambda: "token")
    monkeypatch.setattr(client, "_put_file", lambda *_args: responses.pop(0))

    with pytest.raises(OpenListApiError, match="失效"):
        client.upload(media, "quark:/DouyinBiliRecorder/a.mp4", threading.Event())
