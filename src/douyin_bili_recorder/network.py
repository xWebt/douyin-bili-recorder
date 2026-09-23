from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Any


def detect_system_proxy() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key)
        if value:
            return value
    if sys.platform != "darwin":
        return None
    try:
        output = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    values: dict[str, str] = {}
    for line in output.splitlines():
        match = re.match(r"\s*([A-Za-z]+)\s*:\s*(.+?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2)
    host = values.get("HTTPSProxy") or values.get("HTTPProxy") or values.get("SOCKSProxy")
    port = values.get("HTTPSPort") or values.get("HTTPPort") or values.get("SOCKSPort")
    enabled = values.get("HTTPSEnable") or values.get("HTTPEnable") or values.get("SOCKSEnable")
    if host and port and enabled == "1":
        scheme = "socks5" if "SOCKSProxy" in values and values.get("SOCKSEnable") == "1" else "http"
        return f"{scheme}://{host}:{port}"
    return None


def session_proxies(proxy: str | None = None) -> dict[str, str]:
    selected = proxy or detect_system_proxy()
    if not selected:
        return {}
    host = selected.rsplit("@", 1)[-1]
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "127.0.0.1,localhost"
    return {
        "http": selected,
        "https": selected,
        "all": selected,
        "no_proxy": no_proxy,
        "host": host,
    }


def public_proxy_description(proxy: str | None = None) -> str:
    selected = proxy or detect_system_proxy()
    return selected or "direct"


def proxy_payload(value: str) -> dict[str, Any]:
    return {"proxy": value} if value else {}
