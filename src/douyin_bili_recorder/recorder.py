from __future__ import annotations

import logging
import json
import socket
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, TargetConfig
from .process import ProcessRunner, RunningProcess
from .paths import safe_path_name
from .timeutil import parse_duration_seconds


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

    def start(
        self,
        target: TargetConfig,
        session_dir: Path,
    ) -> RunningProcess:
        if target.record_danmaku:
            return self._start_danmaku_server(target, session_dir)
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
        return self.runner.start(command)

    def _start_danmaku_server(self, target: TargetConfig, session_dir: Path) -> RunningProcess:
        config_path = self._write_danmaku_config(target, session_dir)
        runtime_dir = session_dir / ".danmaku-runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        command = [
            self.config.biliup_bin,
            "server",
            "--bind",
            "127.0.0.1",
            "--port",
            str(self._free_port()),
            "--config",
            str(config_path),
        ]
        return self.runner.start(command, cwd=runtime_dir)

    def _write_danmaku_config(self, target: TargetConfig, session_dir: Path) -> Path:
        config_dir = self.config.data_dir / "danmaku-configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{safe_path_name(target.name)}-{session_dir.name}.toml"
        segment_seconds = parse_duration_seconds(self.config.segment_time)
        hours, remainder = divmod(segment_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        segment_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        quality = {
            "origin": "origin",
            "1080p": "uhd",
            "720p": "hd",
            "480p": "sd",
        }.get(self.config.quality, "origin")
        filename_prefix = "%Y-%m-%dT%H_%M_%S{title}"
        streamer_key = json.dumps(target.name, ensure_ascii=False)
        lines = [
            'downloader = "stream-gears"',
            f"segment_time = {json.dumps(segment_time)}",
            "file_size = 1099511627776",
            "filtering_threshold = 0",
            f"filename_prefix = {json.dumps(filename_prefix)}",
            'uploader = "Noop"',
            "douyin_quality = " + json.dumps(quality),
            "douyin_danmaku = true",
            "use_live_cover = false",
            "delay = 0",
            "event_loop_interval = 5",
            "checker_sleep = 1",
            "pool1_size = 2",
            "pool2_size = 2",
            "",
            f"[streamers.{streamer_key}]",
            f"url = [{json.dumps(target.url)}]",
            f"title = {json.dumps(target.name, ensure_ascii=False)}",
            'postprocessor = [{ run = "true" }]',
        ]
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return config_path

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

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
