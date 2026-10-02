from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests

from .network import detect_system_proxy, session_proxies


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
URL_RE = re.compile(r"https?://[^\s<>\"'\[\]()]+")
URL_TRAILING_CHARS = ".,;:!?，。；：！？、）)]}】》"


def extract_shared_url(text: str) -> str:
    match = URL_RE.search(text)
    if match is None:
        return text.strip()
    return match.group(0).rstrip(URL_TRAILING_CHARS)


@dataclass(slots=True)
class ResolvedTarget:
    input_url: str
    canonical_url: str
    anchor_name: str
    sec_uid: str
    web_rid: str
    room_id: str
    live: bool
    room_title: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_url": self.input_url,
            "canonical_url": self.canonical_url,
            "anchor_name": self.anchor_name,
            "sec_uid": self.sec_uid,
            "web_rid": self.web_rid,
            "room_id": self.room_id,
            "live": self.live,
            "room_title": self.room_title,
        }


class DouyinResolver:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = self._new_session()
        self.proxy_session: requests.Session | None = None

    def _new_session(self, proxies: dict[str, str] | None = None) -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        session.proxies.update(proxies or {})
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Referer": "https://live.douyin.com/",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        return session

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        try:
            return self.session.get(url, timeout=self.timeout, **kwargs)
        except requests.RequestException:
            proxy = detect_system_proxy()
            if not proxy:
                raise
            if self.proxy_session is None:
                self.proxy_session = self._new_session(session_proxies(proxy))
            return self.proxy_session.get(url, timeout=self.timeout, **kwargs)

    def resolve(self, url: str, *, check_live: bool = True) -> ResolvedTarget:
        shared_url = extract_shared_url(url)
        final_url = self._follow_redirect(shared_url)
        share_room = self._resolve_webcast_share(final_url)
        if share_room:
            web_rid = str(share_room.get("web_rid") or "")
            room_id = str(share_room.get("room_id") or "")
            canonical_room = web_rid or room_id
            return ResolvedTarget(
                input_url=url,
                canonical_url=f"https://live.douyin.com/{canonical_room}" if canonical_room else final_url,
                anchor_name=str(share_room.get("anchor_name") or ""),
                sec_uid=str(share_room.get("sec_uid") or ""),
                web_rid=web_rid,
                room_id=room_id,
                live=bool(share_room.get("live")),
                room_title=str(share_room.get("room_title") or ""),
            )
        sec_uid = self._extract_sec_uid(final_url)
        web_rid = self._extract_web_rid(final_url)
        room_alias = ""
        anchor_name = ""
        room_title = ""
        room_id = ""
        profile_live: bool | None = None

        if sec_uid and not web_rid:
            profile = self._resolve_profile(final_url)
            web_rid = str(profile.get("web_rid") or "")
            room_alias = str(profile.get("room_alias") or "")
            room_id = str(profile.get("room_id") or "")
            anchor_name = str(profile.get("anchor_name") or "")
            room_title = str(profile.get("room_title") or "")
            if "live" in profile:
                profile_live = bool(profile["live"])

        if web_rid and (not anchor_name or not room_id or (check_live and profile_live is None)):
            status = self._room_status(web_rid)
            web_rid = str(status.get("web_rid") or web_rid)
            room_id = str(status.get("room_id") or room_id)
            anchor_name = str(status.get("anchor_name") or anchor_name)
            room_title = str(status.get("room_title") or room_title)
            live = bool(status.get("live"))
        else:
            live = bool(profile_live)

        canonical_room = web_rid or room_alias
        canonical_url = f"https://live.douyin.com/{canonical_room}" if canonical_room else final_url
        return ResolvedTarget(
            input_url=url,
            canonical_url=canonical_url,
            anchor_name=anchor_name,
            sec_uid=sec_uid,
            web_rid=web_rid,
            room_id=room_id,
            live=live,
            room_title=room_title,
        )

    def _follow_redirect(self, url: str) -> str:
        if "v.douyin.com" not in url:
            return url
        response = self._get(url, allow_redirects=True)
        return str(response.url)

    def _resolve_webcast_share(self, url: str) -> dict[str, Any]:
        if "webcast.amemv.com" not in url and "/douyin/webcast/reflow/" not in url:
            return {}
        try:
            response = self._get(url)
            response.encoding = "utf-8"
            text = response.text
        except requests.RequestException:
            return {}
        short_id = self._first_match(text, r'(?s)\\"owner\\":\{.*?\\"shortId\\":(\d+)')
        if not short_id:
            short_id = self._first_match(text, r'(?s)"owner":\{.*?"shortId":(\d+)')
        if not short_id:
            return {}
        nickname = self._first_match(text, r'(?s)\\"owner\\":\{.*?\\"nickname\\":\\"([^"\\]+)')
        if not nickname:
            nickname = self._first_match(text, r'(?s)"owner":\{.*?"nickname":"([^"]+)')
        title = self._first_match(text, r'\\"title\\":\\"([^"\\]+)')
        room_id = self._first_match(url, r'/reflow/(\d+)')
        sec_uid = self._first_match(url, r'sec_user_id=([^&]+)')
        return {
            "web_rid": short_id,
            "room_id": room_id,
            "anchor_name": nickname,
            "room_title": title,
            "sec_uid": sec_uid,
            "live": True,
        }

    def _resolve_profile(self, url: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        sec_uid = self._extract_sec_uid(url)
        if not sec_uid:
            return result

        try:
            response = self._get(
                "https://www.iesdouyin.com/web/api/v2/user/info/",
                params={"sec_uid": sec_uid},
            )
            user = (response.json().get("user_info") or {})
            if user.get("nickname"):
                result["anchor_name"] = str(user.get("nickname"))
            if user.get("unique_id"):
                result["room_alias"] = str(user.get("unique_id"))
        except (requests.RequestException, ValueError, AttributeError):
            pass

        try:
            response = self._get("https://webcast.amemv.com/webcast/room/reflow/info/", params={
                "room_id": "2",
                "sec_user_id": sec_uid,
                "type_id": "0",
                "live_id": "1",
                "version_code": "99.99.99",
                "app_id": "1128",
                "aid": "6383",
            })
            room = ((response.json().get("data") or {}).get("room") or {})
            owner = room.get("owner") or {}
            numeric_web_rid = owner.get("web_rid") or room.get("web_rid")
            if numeric_web_rid:
                result["web_rid"] = str(numeric_web_rid)
            if room.get("id_str") or room.get("id"):
                result["room_id"] = str(room.get("id_str") or room.get("id"))
            if owner.get("nickname"):
                result["anchor_name"] = str(owner.get("nickname"))
            if room.get("title"):
                result["room_title"] = str(room.get("title"))
            result["live"] = int(room.get("status") or 0) == 2
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            pass

        if result.get("web_rid"):
            return result

        try:
            text = self._get(url).text
            for key, pattern in (
                ("web_rid", r'web_rid["\\:]+\s*["\']?(\d+)'),
                ("room_id", r'room_id["\\:]+\s*["\']?(\d+)'),
                ("anchor_name", r'nickname["\\:]+\s*["\']([^"\']+)'),
                ("room_title", r'room_title["\\:]+\s*["\']([^"\']+)'),
            ):
                value = self._first_match(text, pattern)
                if value and not result.get(key):
                    result[key] = value
        except requests.RequestException:
            pass
        return {key: value for key, value in result.items() if value not in (None, "")}

    def _room_status(self, web_rid: str) -> dict[str, Any]:
        if not web_rid.isdigit():
            page_status = self._room_status_from_page(web_rid)
            if page_status is not None:
                return page_status
        endpoint = "https://live.douyin.com/webcast/room/web/enter/"
        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "enter_from": "web_live",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "browser_version": "142.0.0.0",
            "web_rid": web_rid,
        }
        try:
            response = self._get(endpoint, params=params)
            payload = response.json()
        except (requests.RequestException, ValueError):
            return self._room_status_from_page(web_rid) or {"web_rid": web_rid, "live": False}

        data = payload.get("data") or {}
        rooms = data.get("data") or []
        room = rooms[0] if isinstance(rooms, list) and rooms else {}
        owner = room.get("owner") or {}
        status = int(room.get("status") or 0)
        return {
            "web_rid": str(owner.get("web_rid") or room.get("web_rid") or web_rid),
            "room_id": str(room.get("id_str") or room.get("id") or ""),
            "anchor_name": str(owner.get("nickname") or ""),
            "room_title": str(room.get("title") or ""),
            "live": status == 2,
        }

    def _room_status_from_page(self, web_rid: str) -> dict[str, Any] | None:
        try:
            response = self._get(f"https://live.douyin.com/{web_rid}")
            text = response.text
        except requests.RequestException:
            return None
        room_match = None
        room_window = ""
        for store_match in re.finditer(r"roomStore", text):
            candidate_window = text[store_match.start() : store_match.start() + 8000]
            expected_web_rid = f'web_rid\\":\\"{web_rid}\\"'
            if expected_web_rid not in candidate_window:
                continue
            candidate = re.search(r'roomId\\":\\"(\d+)\\"', candidate_window)
            if candidate is None:
                candidate = re.search(r'room_id\\":\\"(\d+)\\"', candidate_window)
            if candidate is not None:
                room_match = candidate
                room_window = candidate_window
                break
        if room_match is None:
            room_match = re.search(r'roomId\\":\\"(\d+)\\"', text)
            room_window = text
        if not room_match:
            return None
        room_id = room_match.group(1)
        room_text = room_window[room_match.start() : room_match.start() + 4000]
        window = room_text or text[room_match.start() : room_match.start() + 4000]
        status_match = re.search(r'status\\":(\d+)', window)
        title_match = re.search(r'title\\":\\"([^"\\]*)', window)
        resolved_web_rid = self._first_match(text, r'web_rid\\":\\"([^"\\]+)') or web_rid
        return {
            "web_rid": resolved_web_rid,
            "room_id": room_id,
            "anchor_name": "",
            "room_title": title_match.group(1) if title_match else "",
            "live": bool(status_match and int(status_match.group(1)) == 2),
        }

    @staticmethod
    def _extract_sec_uid(url: str) -> str:
        match = re.search(r"/user/([^/?#]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"[?&]sec_uid=([^&#]+)", url)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_web_rid(url: str) -> str:
        match = re.search(r"(?:live\.douyin\.com|douyin\.com/live)/([^/?#]+)", url)
        return match.group(1) if match else ""

    @staticmethod
    def _first_match(text: str, pattern: str) -> str:
        match = re.search(pattern, text)
        return match.group(1) if match else ""
