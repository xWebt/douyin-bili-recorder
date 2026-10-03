from __future__ import annotations

import logging
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord, SessionStatus
from douyin_bili_recorder.pipeline import RecorderService
from douyin_bili_recorder.process import ProcessResult
from douyin_bili_recorder.uploader import BiliupUploader


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args, **_kwargs) -> ProcessResult:
        command = [str(item) for item in args]
        self.commands.append(command)
        return ProcessResult(0, [])


class ExplodingUploader:
    def __init__(self) -> None:
        self.calls = 0

    def upload_part(self, *_args, **_kwargs):  # pragma: no cover - must not run
        self.calls += 1
        raise AssertionError("uploader must not be called for an already finished job")


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
data_dir = "data"

[upload]
cookie_file = "cookies.json"
retry_count = 0

[[targets]]
name = "anchor"
url = "https://live.douyin.com/1"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
    return load_config(config_path)


def test_part_already_appended_uses_bilibili_lookup(tmp_path: Path) -> None:
    config = _config(tmp_path)
    titles = ["anchor｜2026-10-03 20:00 开播｜P01"]
    uploader = BiliupUploader(
        config,
        RecordingRunner(),
        logging.getLogger("test"),
        part_lookup=lambda _bvid: titles,
    )

    assert uploader.part_already_appended("BV0000000001", titles[0]) is True
    assert uploader.part_already_appended("BV0000000001", "another part") is False


def test_part_lookup_failure_does_not_block_upload(tmp_path: Path) -> None:
    config = _config(tmp_path)

    def broken(_bvid: str) -> list[str]:
        raise RuntimeError("network down")

    uploader = BiliupUploader(
        config,
        RecordingRunner(),
        logging.getLogger("test"),
        part_lookup=broken,
    )
    assert uploader.part_already_appended("BV0000000001", "P02") is False


def test_append_skips_when_part_already_exists(tmp_path: Path) -> None:
    config = _config(tmp_path)
    media = tmp_path / "part-001.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status=SessionStatus.RECORDED,
        bvid="BV0000000001",
    )
    runner = RecordingRunner()
    title = "anchor｜2026-10-03 20:00 开播｜P02"
    uploader = BiliupUploader(
        config,
        runner,
        logging.getLogger("test"),
        part_lookup=lambda _bvid: [title],
    )

    result = uploader.upload_part(
        config.targets[0],
        session,
        media,
        part_index=2,
        title=title,
        bvid="BV0000000001",
    )

    assert result.verified is True
    assert result.bvid == "BV0000000001"
    assert not any("append" in command for command in runner.commands)


def test_pipeline_reuses_succeeded_upload_job(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = RecorderService(config, logging.getLogger("test"))
    media = tmp_path / "part-001.mp4"
    media.write_bytes(b"video")
    session = SessionRecord(
        session_id="session",
        target_name="anchor",
        target_url="https://live.douyin.com/1",
        status=SessionStatus.RECORDED,
        parts=[
            SessionPart(
                index=2,
                status="UPLOADING",
                title="anchor｜2026-10-03 20:00 开播｜P02",
                path=str(media),
                size=media.stat().st_size,
            )
        ],
    )
    service.store.save(session)
    service.store.claim_upload_job("bilibili", "session", 2, fingerprint="f")
    service.store.finish_upload_job(
        "bilibili:session:2",
        "SUCCEEDED",
        bvid="BV0000000001",
        message="uploaded",
    )
    uploader = ExplodingUploader()
    service.uploader = uploader  # type: ignore[assignment]

    result = service._upload_part_with_retries(
        config.targets[0],
        session,
        media,
        session.parts[0],
    )

    assert result.verified is True
    assert result.bvid == "BV0000000001"
    assert uploader.calls == 0
    stored = service.store.load("session")
    assert stored.parts[0].status == "UPLOADED"
    assert stored.parts[0].bvid == "BV0000000001"
