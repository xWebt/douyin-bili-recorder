from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.cloud_uploader import RcloneCloudUploader
from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord
from douyin_bili_recorder.process import ProcessResult


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.results: list[ProcessResult] = []

    def run(self, args, **_kwargs) -> ProcessResult:
        command = [str(item) for item in args]
        self.commands.append(command)
        if self.results:
            return self.results.pop(0)
        return ProcessResult(0, ["ok"])


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[cloud]
rclone_bin = "rclone"

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
cloud_backup = true
cloud_provider = "quark"
cloud_remote = "quark:/DouyinBiliRecorder"
""".strip(),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_cloud_uploader_uses_independent_remote_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    media = session_dir / "hour-01.mp4"
    source = session_dir / "hour-01.flv"
    danmaku = session_dir / "hour-01.xml"
    media.write_bytes(b"mp4")
    source.write_bytes(b"flv")
    danmaku.write_text("<i />", encoding="utf-8")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        detected_start_iso="2026-09-30T20:15:00+08:00",
        cloud_backup=True,
        cloud_provider="quark",
        cloud_remote="quark:/DouyinBiliRecorder",
    )
    part = SessionPart(
        index=2,
        status="PENDING",
        path=str(media),
        source_path=str(source),
        danmaku_path=str(danmaku),
    )
    runner = FakeRunner()
    uploader = RcloneCloudUploader(config, runner, logging.getLogger("test"))  # type: ignore[arg-type]

    result = uploader.upload_part(config.targets[0], session, part)

    assert result.uploaded is True
    assert len(result.remote_paths) == 3
    assert result.remote_paths[0] == (
        "quark:/DouyinBiliRecorder/anchor/2026-09-30/P02/hour-01.mp4"
    )
    assert all(command[:2] == ["rclone", "copyto"] for command in runner.commands)


def test_cloud_uploader_rejects_missing_remote(tmp_path: Path) -> None:
    config = _config(tmp_path)
    media = tmp_path / "part.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
    )
    part = SessionPart(index=1, path=str(media))
    uploader = RcloneCloudUploader(
        config,
        FakeRunner(),  # type: ignore[arg-type]
        logging.getLogger("test"),
    )

    target = config.targets[0]
    target.cloud_remote = ""
    try:
        uploader.upload_part(target, session, part)
    except Exception as exc:  # noqa: BLE001
        assert "rclone 格式" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected missing remote to fail")


def test_cloud_uploader_creates_anchor_directory(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = FakeRunner()
    uploader = RcloneCloudUploader(config, runner, logging.getLogger("test"))  # type: ignore[arg-type]

    remote_path = uploader.ensure_anchor_dir(
        "卢某某",
        "quark:/DouyinBiliRecorder",
        rclone_bin="rclone",
    )

    assert remote_path == "quark:/DouyinBiliRecorder/卢某某"
    assert runner.commands == [["rclone", "mkdir", remote_path]]
