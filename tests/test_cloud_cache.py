from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord, SessionStatus
from douyin_bili_recorder.state import SessionStore
from douyin_bili_recorder.webapp import _clear_target_cache


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[storage]
video_dir = "videos"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
cloud_backup = true
cloud_remote = "openlist:/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_clear_cache_preserves_pending_cloud_backup(tmp_path: Path) -> None:
    config = _config(tmp_path)
    media = config.video_dir / "anchor" / "part.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"video")
    store = SessionStore(config.sessions_dir)
    store.save(
        SessionRecord(
            session_id="session",
            target_name="anchor",
            target_url="https://live.douyin.com/1",
            status=SessionStatus.UPLOADED,
            cloud_backup=True,
            cloud_remote="openlist:/DouyinBiliRecorder",
            parts=[
                SessionPart(
                    index=1,
                    status="UPLOADED",
                    path=str(media),
                    cloud_status="PENDING",
                    bvid="BV0000000001",
                )
            ],
        )
    )

    result = _clear_target_cache(config, "anchor")

    assert result["skipped_cloud_pending"] == 1
    assert media.exists()

    session = store.load("session")
    session.parts[0].cloud_status = "UPLOADED"
    store.save(session)
    result = _clear_target_cache(config, "anchor")

    assert result["skipped_cloud_pending"] == 0
    assert not media.exists()
