from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .config import AppConfig
from .encoding import needs_transcode, video_bitrate_kbps
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
            result = self.process_file(source, session_dir)
            if result is not None:
                results.append(result)
        return results

    def process_file(
        self,
        source: Path,
        session_dir: Path,
        *,
        part_index: int | None = None,
    ) -> MediaFile | None:
        uploaded_path = source
        if needs_transcode(self.config.quality, self.config.frame_rate):
            stem = f"part-{part_index:03d}" if part_index is not None else source.stem
            target = session_dir / f"{stem}.mp4"
            if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
                self._transcode(source, target)
            uploaded_path = target
            if not self.config.keep_original_files:
                source.unlink(missing_ok=True)

        if not uploaded_path.exists() or uploaded_path.stat().st_size == 0:
            self.logger.warning("skipping empty media output: %s", uploaded_path)
            return None

        return MediaFile(
            path=str(uploaded_path.relative_to(session_dir)),
            size=uploaded_path.stat().st_size,
            duration_seconds=self.probe_duration(uploaded_path),
            source=str(source.relative_to(session_dir)) if source != uploaded_path else None,
        )

    def _transcode(self, source: Path, target: Path) -> None:
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
        ]
        quality_changed = self.config.quality != "origin"
        fps_changed = self.config.frame_rate != "source"
        if quality_changed or fps_changed:
            if quality_changed:
                height = {"1080p": 1080, "720p": 720, "480p": 480}[self.config.quality]
                command.extend(["-vf", f"scale=-2:{height}"])
            if fps_changed:
                command.extend(["-r", self.config.frame_rate])
            bitrate = video_bitrate_kbps(self.config.quality, self.config.frame_rate)
            if bitrate:
                command.extend(
                    [
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-pix_fmt",
                        "yuv420p",
                        "-b:v",
                        f"{bitrate}k",
                        "-maxrate",
                        f"{int(bitrate * 1.2)}k",
                        "-bufsize",
                        f"{bitrate * 2}k",
                    ]
                )
            else:
                command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
            command.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            command.extend(["-c", "copy", "-bsf:a", "aac_adtstoasc"])
        command.extend(["-movflags", "+faststart", "-avoid_negative_ts", "make_zero", str(target)])
        result = self.runner.run(command)
        if result.returncode != 0 or not target.exists():
            raise RuntimeError(f"failed to convert {source} to {target}")

    def probe_duration(self, path: Path) -> float | None:
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
