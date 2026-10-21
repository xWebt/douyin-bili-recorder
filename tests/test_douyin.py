from __future__ import annotations

import pytest

from douyin_bili_recorder.douyin import (
    DouyinResolver,
    extract_shared_url,
    normalize_share_input,
)


def test_extract_shared_url_accepts_copy_text_and_markdown() -> None:
    text = "长按复制此条消息，打开抖音搜索，查看TA的更多作品。 [https://v.douyin.com/wd0JKyDUQ1A/](https://v.douyin.com/wd0JKyDUQ1A/)"

    assert extract_shared_url(text) == "https://v.douyin.com/wd0JKyDUQ1A/"


def test_extract_shared_url_handles_current_live_and_profile_share_noise() -> None:
    live_text = (
        "#在抖音，记录美好生活#【测试主播】正在直播，来和我一起支持Ta吧。"
        "复制下方链接，打开【抖音】，直接观看直播！ "
        "https://v.douyin.com/LIVE123/\u00a00@5.com :4pm"
    )
    profile_text = (
        "长按复制此条消息，打开抖音搜索，查看TA的更多作品。 "
        "[https://v.douyin.com/PROFILE123/](https://v.douyin.com/PROFILE123/) 4@0.com :1pm"
    )

    assert extract_shared_url(live_text) == "https://v.douyin.com/LIVE123/"
    assert extract_shared_url(profile_text) == "https://v.douyin.com/PROFILE123/"


def test_extract_shared_url_prefers_douyin_link_in_mixed_text() -> None:
    text = (
        "复制这条消息 https://example.com/help 打开抖音，"
        "直播间地址 https://live.douyin.com/123456789?from=share 看看"
    )

    assert extract_shared_url(text) == "https://live.douyin.com/123456789?from=share"


def test_normalize_share_input_accepts_profile_and_live_links() -> None:
    assert normalize_share_input(
        "主页：https://www.douyin.com/user/MS4wLjABAAAA?from_tab_name=main"
    ) == "https://www.douyin.com/user/MS4wLjABAAAA?from_tab_name=main"
    assert normalize_share_input(
        "直播间 https://live.douyin.com/123 复制打开"
    ) == "https://live.douyin.com/123"


def test_normalize_share_input_rejects_non_douyin_text() -> None:
    with pytest.raises(ValueError):
        normalize_share_input("https://example.com/not-douyin")
    with pytest.raises(ValueError):
        normalize_share_input("完全没有链接的分享文案")


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


def test_offline_webcast_share_uses_profile_alias(monkeypatch) -> None:
    resolver = DouyinResolver()
    reflow_url = (
        "https://webcast.amemv.com/douyin/webcast/reflow/7698957329181838080"
        "?sec_user_id=TEST_SEC_UID&share_platform=copy"
    )
    calls: dict[str, str] = {}

    monkeypatch.setattr(resolver, "_follow_redirect", lambda _url: reflow_url)
    monkeypatch.setattr(resolver, "_resolve_webcast_share", lambda _url: {})

    def resolve_profile(url: str) -> dict[str, object]:
        calls["profile"] = url
        return {
            "room_alias": "offline-anchor",
            "anchor_name": "Offline Anchor",
        }

    def room_status(room: str) -> dict[str, object]:
        calls["status"] = room
        return {
            "web_rid": "offline-anchor",
            "room_id": "7698957329181838080",
            "anchor_name": "Offline Anchor",
            "room_title": "",
            "live": False,
        }

    monkeypatch.setattr(resolver, "_resolve_profile", resolve_profile)
    monkeypatch.setattr(resolver, "_room_status", room_status)

    result = resolver.resolve(
        "正在直播，复制下方链接 https://v.douyin.com/LIVE123/ 0@5.com :4pm",
        check_live=True,
    )

    assert calls["profile"] == "https://www.douyin.com/user/TEST_SEC_UID"
    assert calls["status"] == "offline-anchor"
    assert result.canonical_url == "https://live.douyin.com/offline-anchor"
    assert result.anchor_name == "Offline Anchor"
    assert result.room_id == "7698957329181838080"
    assert result.live is False


def test_offline_webcast_share_can_skip_live_check(monkeypatch) -> None:
    resolver = DouyinResolver()

    monkeypatch.setattr(
        resolver,
        "_follow_redirect",
        lambda _url: (
            "https://webcast.amemv.com/douyin/webcast/reflow/7698957329181838080"
            "?sec_user_id=TEST_SEC_UID"
        ),
    )
    monkeypatch.setattr(resolver, "_resolve_webcast_share", lambda _url: {})
    monkeypatch.setattr(
        resolver,
        "_resolve_profile",
        lambda _url: {
            "room_alias": "offline-anchor",
            "anchor_name": "Offline Anchor",
        },
    )
    monkeypatch.setattr(
        resolver,
        "_room_status",
        lambda _room: (_ for _ in ()).throw(AssertionError("status should not be checked")),
    )

    result = resolver.resolve(
        "主页分享 https://v.douyin.com/PROFILE123/ 4@0.com :1pm",
        check_live=False,
    )

    assert result.canonical_url == "https://live.douyin.com/offline-anchor"
    assert result.sec_uid == "TEST_SEC_UID"
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
