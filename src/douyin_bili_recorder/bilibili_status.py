from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .network import detect_system_proxy, session_proxies


ARCHIVES_API = "https://member.bilibili.com/x/web/archives"
VIEW_API = "https://member.bilibili.com/x/vupre/web/archive/view"
REFERER = "https://member.bilibili.com/platform/upload/video/frame"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


STATE_LABELS = {
    "is_pubing": "审核中",
    "pubed": "已发布",
    "not_pubed": "未通过",
    "open": "开放浏览",
    "self": "仅自己可见",
}


@dataclass(slots=True)
class SubmissionStatus:
    bvid: str
    title: str
    state: str
    state_desc: str
    duration_seconds: int = 0
    created_epoch: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bvid": self.bvid,
            "title": self.title,
            "state": self.state,
            "state_desc": self.state_desc,
            "duration_seconds": self.duration_seconds,
            "created_epoch": self.created_epoch,
        }


class BilibiliSubmissionClient:
    def __init__(self, cookie_file: Path, timeout: int = 15) -> None:
        self.cookie_file = cookie_file
        self.timeout = timeout
        self.cookies = self._load_cookies()
        self.session = self._new_session()
        self.proxy_session: requests.Session | None = None
        self._detail_cache: dict[str, tuple[float, SubmissionStatus | None]] = {}

    def list_for_bvids(self, bvids: set[str]) -> list[SubmissionStatus]:
        if not bvids:
            return []
        archives = self._list_archives()
        by_bvid = {status.bvid: status for status in archives}
        result: list[SubmissionStatus] = []
        for bvid in sorted(bvids):
            status = by_bvid.get(bvid)
            if status is None:
                status = self._detail(bvid)
            if status is not None:
                result.append(status)
        return result

    def _list_archives(self) -> list[SubmissionStatus]:
        response = self._request(
            "GET",
            ARCHIVES_API,
            params={
                "pn": 1,
                "ps": 50,
                "status": "is_pubing,pubed,not_pubed",
            },
        )
        data = self._expect_success(response, "获取B站稿件列表")
        audits = data.get("arc_audits") if isinstance(data, dict) else None
        if not isinstance(audits, list):
            return []
        result: list[SubmissionStatus] = []
        for item in audits:
            archive = item.get("Archive") if isinstance(item, dict) else None
            if not isinstance(archive, dict):
                continue
            parsed = self._parse_archive(archive)
            if parsed is not None:
                result.append(parsed)
        return result

    def _detail(self, bvid: str) -> SubmissionStatus | None:
        cached = self._detail_cache.get(bvid)
        if cached is not None and time.time() - cached[0] < 60:
            return cached[1]
        try:
            response = self._request("GET", VIEW_API, params={"bvid": bvid})
            data = self._expect_success(response, f"获取稿件 {bvid} 状态")
        except RuntimeError:
            self._detail_cache[bvid] = (time.time(), None)
            return None
        archive = data.get("archive") if isinstance(data, dict) else None
        if not isinstance(archive, dict):
            archive = data if isinstance(data, dict) else {}
        parsed = self._parse_archive(archive, fallback_bvid=bvid)
        self._detail_cache[bvid] = (time.time(), parsed)
        return parsed

    @staticmethod
    def _parse_archive(archive: dict[str, Any], *, fallback_bvid: str = "") -> SubmissionStatus | None:
        bvid = str(archive.get("bvid") or archive.get("bv_id") or fallback_bvid).strip()
        if not bvid:
            return None
        primary_state = str(archive.get("primary_state") or archive.get("state") or "").strip()
        state_desc = str(archive.get("state_desc") or "").strip()
        if not state_desc:
            state_desc = STATE_LABELS.get(primary_state, primary_state or "状态未知")
        duration = int(archive.get("duration") or archive.get("duration_seconds") or 0)
        created = int(archive.get("ctime") or archive.get("pubtime") or archive.get("created") or 0)
        return SubmissionStatus(
            bvid=bvid,
            title=str(archive.get("title") or ""),
            state=primary_state,
            state_desc=state_desc,
            duration_seconds=max(0, duration),
            created_epoch=max(0, created),
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
        return payload.get("data") or {}
