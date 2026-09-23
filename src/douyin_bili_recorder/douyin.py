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
        final_url = self._follow_redirect(url.strip())
        sec_uid = self._extract_sec_uid(final_url)
        web_rid = self._extract_web_rid(final_url)
        anchor_name = ""
        room_title = ""
        room_id = ""

        if sec_uid and not web_rid:
            profile = self._resolve_profile(final_url)
            web_rid = str(profile.get("web_rid") or "")
            room_id = str(profile.get("room_id") or "")
            anchor_name = str(profile.get("anchor_name") or "")
            room_title = str(profile.get("room_title") or "")

        if web_rid and (not anchor_name or not room_id or check_live):
            status = self._room_status(web_rid)
            web_rid = str(status.get("web_rid") or web_rid)
            room_id = str(status.get("room_id") or room_id)
            anchor_name = str(status.get("anchor_name") or anchor_name)
            room_title = str(status.get("room_title") or room_title)
            live = bool(status.get("live"))
        else:
            live = False

        canonical_url = f"https://live.douyin.com/{web_rid}" if web_rid else final_url
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

    def _resolve_profile(self, url: str) -> dict[str, str]:
        result: dict[str, str] = {}
        sec_uid = self._extract_sec_uid(url)
        if sec_uid:
            try:
                response = self._get(
                    "https://www.iesdouyin.com/web/api/v2/user/info/",
                    params={"sec_uid": sec_uid},
                )
                payload = response.json()
                user = payload.get("user_info") or {}
                result["anchor_name"] = str(user.get("nickname") or "")
                for entry in user.get("card_entries") or []:
                    if int(entry.get("type") or 0) != 6:
                        continue
                    goto = str(entry.get("goto_url") or "")
                    room_id = self._first_match(goto, r"anchor_id%3D(\d+)")
                    if room_id:
                        result["room_id"] = room_id
                    break
            except (requests.RequestException, ValueError, AttributeError):
                pass
        try:
            response = self._get(url)
            text = response.text
            result["web_rid"] = self._first_match(text, r'web_rid["\\:]+\s*["\']?(\d+)')
            result["room_id"] = self._first_match(text, r'room_id["\\:]+\s*["\']?(\d+)')
            result.setdefault("anchor_name", self._first_match(text, r'nickname["\\:]+\s*["\']([^"\']+)'))
            result["room_title"] = self._first_match(text, r'room_title["\\:]+\s*["\']([^"\']+)')
        except requests.RequestException:
            pass

        if not result.get("web_rid"):
            if sec_uid:
                api = "https://webcast.amemv.com/webcast/room/reflow/info/"
                params = {
                    "room_id": "2",
                    "sec_user_id": sec_uid,
                    "type_id": "0",
                    "live_id": "1",
                    "version_code": "99.99.99",
                    "app_id": "1128",
                    "aid": "6383",
                }
                try:
                    response = self._get(api, params=params)
                    payload = response.json()
                    room = ((payload.get("data") or {}).get("room") or {})
                    owner = room.get("owner") or {}
                    if owner.get("web_rid") or room.get("web_rid"):
                        result["web_rid"] = str(owner.get("web_rid") or room.get("web_rid"))
                    if room.get("id_str") or room.get("id"):
                        result["room_id"] = str(room.get("id_str") or room.get("id"))
                    if owner.get("nickname"):
                        result["anchor_name"] = str(owner.get("nickname"))
                    if room.get("title"):
                        result["room_title"] = str(room.get("title"))
                except (requests.RequestException, ValueError, AttributeError):
                    pass
        return {key: value for key, value in result.items() if value}

    def _room_status(self, web_rid: str) -> dict[str, Any]:
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
            return {"web_rid": web_rid, "live": False}

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

    @staticmethod
    def _extract_sec_uid(url: str) -> str:
        match = re.search(r"/user/([^/?#]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"[?&]sec_uid=([^&#]+)", url)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_web_rid(url: str) -> str:
        match = re.search(r"(?:live\.douyin\.com|douyin\.com/live)/(\d+)", url)
        return match.group(1) if match else ""

    @staticmethod
    def _first_match(text: str, pattern: str) -> str:
        match = re.search(pattern, text)
        return match.group(1) if match else ""
