from __future__ import annotations

from douyin_bili_recorder.douyin import DouyinResolver, extract_shared_url


def test_extract_shared_url_accepts_copy_text_and_markdown() -> None:
    text = "长按复制此条消息，打开抖音搜索，查看TA的更多作品。 [https://v.douyin.com/wd0JKyDUQ1A/](https://v.douyin.com/wd0JKyDUQ1A/)"

    assert extract_shared_url(text) == "https://v.douyin.com/wd0JKyDUQ1A/"


def test_resolve_uses_live_alias_when_anchor_is_offline(monkeypatch) -> None:
    resolver = DouyinResolver()
    monkeypatch.setattr(
        resolver,
        "_resolve_profile",
        lambda _url: {
            "room_alias": "223yuu",
            "anchor_name": "阿尔萨鱼",
            "live": False,
        },
    )

    result = resolver.resolve("https://www.douyin.com/user/test")

    assert result.canonical_url == "https://live.douyin.com/223yuu"
    assert result.anchor_name == "阿尔萨鱼"
    assert result.live is False


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


def test_webcast_share_uses_anchor_short_id(monkeypatch) -> None:
    class TextResponse:
        text = r'{\"owner\":{\"id\":2344620028077864,\"shortId\":89996101660,\"nickname\":\"凡晨\"},\"title\":\"测试直播\"}'

    resolver = DouyinResolver()
    monkeypatch.setattr(resolver, "_get", lambda _url, **_kwargs: TextResponse())

    result = resolver._resolve_webcast_share(
        "https://webcast.amemv.com/douyin/webcast/reflow/7692116106240084786?sec_user_id=test"
    )

    assert result["web_rid"] == "89996101660"
    assert result["room_id"] == "7692116106240084786"
    assert result["live"] is True
