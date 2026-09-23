from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .network import detect_system_proxy, session_proxies


CREATIVE_BASE = "https://member.bilibili.com/x2/creative/web"
VIEW_API = "https://api.bilibili.com/x/web-interface/view"
REFERER = "https://member.bilibili.com/platform/upload/video/frame"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class CollectionInfo:
    id: int
    title: str
    section_id: int
    section_title: str


class BilibiliCollectionManager:
    def __init__(self, cookie_file: Path, timeout: int = 20) -> None:
        self.cookie_file = cookie_file
        self.timeout = timeout
        self.cookies = self._load_cookies()
        self.csrf = self.cookies.get("bili_jct", "")
        self.session = self._new_session()
        self.proxy_session: requests.Session | None = None

    def ensure_collection(self, title: str, bvid: str) -> CollectionInfo:
        existing = self.find_collection(title)
        if existing is not None:
            return existing
        video = self.video_info(bvid)
        cover = str(video.get("pic") or "")
        if not cover:
            raise RuntimeError("Bilibili video cover is not ready for collection creation")
        season_id = self.create_collection(title, cover)
        collection = None
        for _ in range(5):
            collection = self.find_collection_by_id(season_id)
            if collection is not None:
                break
            time.sleep(2)
        if collection is None:
            raise RuntimeError(f"created collection {season_id} but could not resolve its default section")
        return collection

    def add_video(self, collection: CollectionInfo, bvid: str, title: str = "") -> None:
        video = self.video_info(bvid)
        aid = int(video.get("aid") or 0)
        cid = int((video.get("pages") or [{}])[0].get("cid") or 0)
        if aid <= 0 or cid <= 0:
            raise RuntimeError(f"could not resolve aid/cid for {bvid}")
        payload = {
            "sectionId": collection.section_id,
            "episodes": [
                {
                    "aid": aid,
                    "cid": cid,
                    "title": title or str(video.get("title") or ""),
                    "charging_pay": 0,
                }
            ],
        }
        response = self._request(
            "POST",
            f"{CREATIVE_BASE}/season/section/episodes/add",
            params={"csrf": self.csrf},
            json=payload,
        )
        self._expect_success(response, "添加稿件到B站合集")

    def find_collection(self, title: str) -> CollectionInfo | None:
        for item in self.list_collections():
            season = item.get("season") or {}
            if str(season.get("title") or "").strip() != title.strip():
                continue
            return self._collection_from_item(item)
        return None

    def find_collection_by_id(self, season_id: int) -> CollectionInfo | None:
        for item in self.list_collections():
            season = item.get("season") or {}
            if int(season.get("id") or 0) == season_id:
                return self._collection_from_item(item)
        return None

    def list_collections(self) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"{CREATIVE_BASE}/seasons",
            params={"pn": 1, "ps": 50, "order": "mtime", "sort": "desc", "draft": 1},
        )
        data = self._expect_success(response, "获取B站合集列表")
        if isinstance(data, dict):
            seasons = data.get("seasons")
            return seasons if isinstance(seasons, list) else []
        return []

    def create_collection(self, title: str, cover: str) -> int:
        response = self._request(
            "POST",
            f"{CREATIVE_BASE}/season/add",
            data={
                "title": title,
                "desc": "",
                "cover": cover,
                "season_price": "0",
                "csrf": self.csrf,
            },
        )
        data = self._expect_success(response, "创建B站合集")
        season_id = int(data or 0)
        if season_id <= 0:
            raise RuntimeError("Bilibili collection creation returned no season id")
        return season_id

    def video_info(self, bvid: str) -> dict[str, Any]:
        response = self._request("GET", VIEW_API, params={"bvid": bvid})
        return self._expect_success(response, "获取B站视频信息")

    def _collection_from_item(self, item: dict[str, Any]) -> CollectionInfo:
        season = item.get("season") or {}
        sections = ((item.get("sections") or {}).get("sections") or [])
        section = next((entry for entry in sections if int(entry.get("id") or 0) > 0), None)
        if section is None:
            raise RuntimeError("Bilibili collection has no default section")
        return CollectionInfo(
            id=int(season.get("id") or 0),
            title=str(season.get("title") or ""),
            section_id=int(section.get("id") or 0),
            section_title=str(section.get("title") or "正片"),
        )

    def _load_cookies(self) -> dict[str, str]:
        if not self.cookie_file.exists():
            raise RuntimeError(f"Bilibili cookie file does not exist: {self.cookie_file}")
        payload = json.loads(self.cookie_file.read_text(encoding="utf-8"))
        cookies = ((payload.get("cookie_info") or {}).get("cookies") or [])
        result = {str(item.get("name")): str(item.get("value")) for item in cookies if item.get("name")}
        if not result:
            raise RuntimeError("Bilibili cookies are missing or invalid")
        return result

    def _new_session(self, proxies: dict[str, str] | None = None) -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        session.proxies.update(proxies or {})
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Referer": REFERER,
                "Origin": "https://member.bilibili.com",
                "Cookie": "; ".join(f"{key}={value}" for key, value in self.cookies.items()),
            }
        )
        return session

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            return self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException:
            proxy = detect_system_proxy()
            if not proxy:
                raise
            if self.proxy_session is None:
                self.proxy_session = self._new_session(session_proxies(proxy))
            return self.proxy_session.request(method, url, timeout=self.timeout, **kwargs)

    @staticmethod
    def _expect_success(response: requests.Response, action: str) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{action}失败: HTTP {response.status_code}") from exc
        if int(payload.get("code", -1)) != 0:
            raise RuntimeError(f"{action}失败: {payload.get('message') or payload.get('msg') or payload.get('code')}")
        return payload.get("data")
