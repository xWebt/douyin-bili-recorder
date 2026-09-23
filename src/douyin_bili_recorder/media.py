from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from .config import AppConfig
from .models import MediaFile
from .process import ProcessRunner
from .recorder import discover_media


class MediaProcessor:
    def __init__(self, config: AppConfig, runner: ProcessRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger

    def process(self, session_dir: Path) -> list[MediaFile]:
        results: list[MediaFile] = []
        for source in discover_media(session_dir, self.config.min_file_size_mb):
            uploaded_path = source
            if source.suffix.lower() != ".mp4":
                target = source.with_suffix(".mp4")
                if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
                    self._remux(source, target)
                uploaded_path = target
                if not self.config.keep_original_files:
                    source.unlink(missing_ok=True)

            if not uploaded_path.exists() or uploaded_path.stat().st_size == 0:
                self.logger.warning("skipping empty media output: %s", uploaded_path)
                continue

            duration = self._probe_duration(uploaded_path)
            checksum = self._sha256(uploaded_path)
            results.append(
                MediaFile(
                    path=str(uploaded_path.relative_to(session_dir)),
                    size=uploaded_path.stat().st_size,
                    duration_seconds=duration,
                    sha256=checksum,
                    source=str(source.relative_to(session_dir)) if source != uploaded_path else None,
                )
            )
        return results

    def _remux(self, source: Path, target: Path) -> None:
        command = [
            self.config.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-fflags",
            "+genpts+igndts",
            "-i",
            str(source),
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            str(target),
        ]
        result = self.runner.run(command)
        if result.returncode != 0 or not target.exists():
            raise RuntimeError(f"failed to remux {source} to {target}")

    def _probe_duration(self, path: Path) -> float | None:
        command = [
            self.config.ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            self.logger.warning("ffprobe failed for %s: %s", path, completed.stderr.strip())
            return None
        try:
            payload = json.loads(completed.stdout)
            return float(payload["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
