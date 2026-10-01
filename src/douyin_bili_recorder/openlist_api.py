from __future__ import annotations

import base64
import configparser
import hashlib
import subprocess
import threading
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util import Counter


_RCLONE_CRYPT_KEY = bytes(
    (
        0x9C, 0x93, 0x5B, 0x48, 0x73, 0x0A, 0x55, 0x4D,
        0x6B, 0xFD, 0x7C, 0x63, 0xC8, 0x86, 0xA9, 0x2B,
        0xD3, 0x90, 0x19, 0x8E, 0xB8, 0x12, 0x8A, 0xFB,
        0xF4, 0xDE, 0x16, 0x2B, 0x8B, 0x95, 0xF6, 0x38,
    )
)
_STATIC_HASH_SALT = "https://github.com/alist-org/alist"


class OpenListApiError(RuntimeError):
    pass


class _CancellableReader:
    def __init__(self, path: Path, cancel_event: threading.Event) -> None:
        self.path = path
        self.cancel_event = cancel_event
        self.handle = path.open("rb")
        self.size = path.stat().st_size

    def __len__(self) -> int:
        return self.size

    def read(self, size: int = -1) -> bytes:
        if self.cancel_event.is_set():
            raise OpenListApiError("网盘备份已停止")
        return self.handle.read(size)

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> _CancellableReader:
        return self

    def __exit__(self, *_args) -> None:
        self.close()


class OpenListApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        remote_name: str,
        timeout_seconds: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.remote_name = remote_name
        self.timeout_seconds = timeout_seconds
        self._token = ""
        self._session = requests.Session()

    @classmethod
    def from_rclone_remote(
        cls,
        remote: str,
        *,
        rclone_bin: str,
        timeout_seconds: int,
    ) -> OpenListApiClient | None:
        if ":" not in remote:
            return None
        remote_name, _remote_path = remote.split(":", 1)
        remote_name = remote_name.strip()
        if not remote_name:
            return None
        try:
            completed = subprocess.run(
                [rclone_bin, "config", "file"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        config_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not config_lines:
            return None
        config_path = Path(config_lines[-1]).expanduser()
        if not config_path.is_file():
            return None
        parser = configparser.ConfigParser()
        parser.read(config_path)
        if not parser.has_section(remote_name):
            return None
        if parser.get(remote_name, "type", fallback="").strip().lower() != "webdav":
            return None
        parsed = urlparse(parser.get(remote_name, "url", fallback="").strip())
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port != 5244:
            return None
        username = parser.get(remote_name, "user", fallback="").strip()
        obscured = parser.get(remote_name, "pass", fallback="").strip()
        if not username or not obscured:
            return None
        try:
            password = _reveal_rclone_password(obscured)
        except (ValueError, UnicodeDecodeError):
            return None
        return cls(
            base_url=f"{parsed.scheme}://{parsed.netloc}",
            username=username,
            password=password,
            remote_name=remote_name,
            timeout_seconds=timeout_seconds,
        )

    def upload(
        self,
        local_path: Path,
        remote_path: str,
        cancel_event: threading.Event,
    ) -> None:
        api_path = self.remote_to_api_path(remote_path)
        token = self._login()
        response = self._put_file(local_path, api_path, token, cancel_event)
        if response.status_code == 401:
            self._token = ""
            token = self._login()
            response = self._put_file(local_path, api_path, token, cancel_event)
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenListApiError(f"OpenList 上传返回非 JSON 响应：HTTP {response.status_code}") from exc
        if response.status_code != 200 or int(payload.get("code", 0)) != 200:
            message = str(payload.get("message") or f"HTTP {response.status_code}")
            raise OpenListApiError(f"OpenList 原生上传失败：{message}")

    def remote_to_api_path(self, remote_path: str) -> str:
        prefix = f"{self.remote_name}:"
        if not remote_path.startswith(prefix):
            raise OpenListApiError("OpenList 远端路径与 rclone remote 不匹配")
        path = remote_path[len(prefix):]
        return path if path.startswith("/") else f"/{path}"

    def _login(self) -> str:
        if self._token:
            return self._token
        static_hash = hashlib.sha256(
            f"{self.password}-{_STATIC_HASH_SALT}".encode("utf-8")
        ).hexdigest()
        try:
            response = self._session.post(
                f"{self.base_url}/api/auth/login/hash",
                json={
                    "username": self.username,
                    "password": static_hash,
                    "otp_code": "",
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise OpenListApiError(f"OpenList 登录失败：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenListApiError("OpenList 登录返回非 JSON 响应") from exc
        token = str((payload.get("data") or {}).get("token") or "")
        if response.status_code != 200 or int(payload.get("code", 0)) != 200 or not token:
            raise OpenListApiError(str(payload.get("message") or "OpenList 登录失败"))
        self._token = token
        return token

    def _put_file(
        self,
        local_path: Path,
        api_path: str,
        token: str,
        cancel_event: threading.Event,
    ) -> requests.Response:
        headers = {
            "Authorization": token,
            "File-Path": quote(api_path, safe="/"),
            "Content-Type": "application/octet-stream",
            "Content-Length": str(local_path.stat().st_size),
            "As-Task": "false",
        }
        try:
            with _CancellableReader(local_path, cancel_event) as reader:
                return self._session.put(
                    f"{self.base_url}/api/fs/put",
                    headers=headers,
                    data=reader,
                    timeout=(30, self.timeout_seconds),
                )
        except requests.RequestException as exc:
            raise OpenListApiError(f"OpenList 原生上传失败：{exc}") from exc


def _reveal_rclone_password(value: str) -> str:
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(raw) < AES.block_size:
        raise ValueError("obscured value is too short")
    iv = raw[: AES.block_size]
    ciphertext = raw[AES.block_size:]
    counter = Counter.new(128, initial_value=int.from_bytes(iv, "big"))
    plaintext = AES.new(_RCLONE_CRYPT_KEY, AES.MODE_CTR, counter=counter).decrypt(ciphertext)
    return plaintext.decode("utf-8")
