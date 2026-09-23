from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, TargetConfig
from .process import ProcessRunner


@dataclass(slots=True)
class RecordAttempt:
    returncode: int
    lines: list[str]
    media_paths: list[Path]
    timed_out: bool = False

    @property
    def stream_offline(self) -> bool:
        text = "\n".join(self.lines).lower()
        return "stream is offline" in text


class BiliupRecorder:
    def __init__(self, config: AppConfig, runner: ProcessRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger

    def record(
        self,
        target: TargetConfig,
        session_dir: Path,
        *,
        timeout_seconds: int | None = None,
        allow_partials: bool = False,
    ) -> RecordAttempt:
        output_template = session_dir / "%Y-%m-%dT%H_%M_%S{title}"
        command = [
            self.config.biliup_bin,
            "download",
            target.url,
            "-o",
            str(output_template),
            "--split-time",
            self.config.segment_time,
        ]
        result = self.runner.run(command, timeout_seconds=timeout_seconds)
        media_paths = discover_media(
            session_dir,
            self.config.min_file_size_mb,
            allow_partials=allow_partials,
        )
        return RecordAttempt(result.returncode, result.lines, media_paths, result.timed_out)


MEDIA_EXTENSIONS = {".mp4", ".mkv", ".flv", ".ts", ".m4s"}


def discover_media(
    root: Path,
    min_file_size_mb: int = 0,
    *,
    allow_partials: bool = False,
) -> list[Path]:
    minimum = min_file_size_mb * 1024 * 1024
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        is_partial = path.name.lower().endswith(".part")
        if is_partial:
            if not allow_partials:
                continue
            media_name = path.name[: -len(".part")]
        else:
            media_name = path.name
        if Path(media_name).suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        if not (is_partial and allow_partials) and path.stat().st_size < minimum:
            continue
        files.append(path)
    return sorted(files, key=lambda item: (item.stat().st_mtime, str(item)))
