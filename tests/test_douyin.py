from __future__ import annotations

from douyin_bili_recorder.douyin import DouyinResolver


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload

    @property
    def text(self) -> str:
        return ""

    @property
    def url(self) -> str:
        return "https://www.douyin.com/user/test"


def test_profile_resolution_prefers_numeric_live_room(monkeypatch) -> None:
    resolver = DouyinResolver()
    user_payload = {
        "user_info": {
            "nickname": "imxiaoxin",
            "unique_id": "XiaoXinFps",
        }
    }
    reflow_payload = {
        "data": {
            "room": {
                "id_str": "7690059945898756890",
                "status": 2,
                "title": "测试直播",
                "owner": {
                    "nickname": "imxiaoxin",
                    "web_rid": "694562812381",
                },
            }
        }
    }

    def fake_get(url: str, **_kwargs):
        if "user/info" in url:
            return FakeResponse(user_payload)
        if "reflow/info" in url:
            return FakeResponse(reflow_payload)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(resolver, "_get", fake_get)

    result = resolver._resolve_profile("https://www.douyin.com/user/test")

    assert result["web_rid"] == "694562812381"
    assert result["room_id"] == "7690059945898756890"
    assert result["anchor_name"] == "imxiaoxin"
    assert result["live"] is True


def test_resolve_uses_numeric_canonical_live_url(monkeypatch) -> None:
    resolver = DouyinResolver()
    monkeypatch.setattr(
        resolver,
        "_resolve_profile",
        lambda _url: {
            "web_rid": "694562812381",
            "room_id": "7690059945898756890",
            "anchor_name": "imxiaoxin",
            "room_title": "测试直播",
            "live": True,
        },
    )

    result = resolver.resolve("https://www.douyin.com/user/test")

    assert result.canonical_url == "https://live.douyin.com/694562812381"
    assert result.web_rid == "694562812381"
    assert result.live is True
