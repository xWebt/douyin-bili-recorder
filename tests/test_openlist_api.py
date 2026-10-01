from __future__ import annotations

import base64
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util import Counter

from douyin_bili_recorder.openlist_api import (
    OpenListApiClient,
    _RCLONE_CRYPT_KEY,
    _reveal_rclone_password,
)


def _obscure(value: str) -> str:
    iv = bytes(range(16))
    counter = Counter.new(128, initial_value=int.from_bytes(iv, "big"))
    ciphertext = AES.new(_RCLONE_CRYPT_KEY, AES.MODE_CTR, counter=counter).encrypt(value.encode())
    return base64.urlsafe_b64encode(iv + ciphertext).rstrip(b"=").decode()


def test_reveal_rclone_password() -> None:
    assert _reveal_rclone_password(_obscure("openlist-pass")) == "openlist-pass"


def test_openlist_client_from_local_rclone_webdav(tmp_path: Path) -> None:
    config_path = tmp_path / "rclone.conf"
    config_path.write_text(
        """
[quark]
type = webdav
url = http://127.0.0.1:5244/dav
vendor = other
user = admin
pass = {password}
""".format(password=_obscure("secret")),
        encoding="utf-8",
    )
    executable = tmp_path / "rclone"
    executable.write_text(f"#!/bin/sh\necho '{config_path}'\n", encoding="utf-8")
    executable.chmod(0o755)

    client = OpenListApiClient.from_rclone_remote(
        "quark:/quark/DouyinBiliRecorder",
        rclone_bin=str(executable),
        timeout_seconds=60,
    )

    assert client is not None
    assert client.base_url == "http://127.0.0.1:5244"
    assert client.username == "admin"
    assert client.password == "secret"
    assert client.remote_to_api_path("quark:/quark/DouyinBiliRecorder/a.mp4") == (
        "/quark/DouyinBiliRecorder/a.mp4"
    )
