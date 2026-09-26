from __future__ import annotations

import logging
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import AppConfig
from .encoding import video_bitrate_kbps
from .process import ProcessRunner


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def estimate_text_width(text: str, font_size: int) -> int:
    width = 0.0
    for char in text:
        width += font_size if ord(char) > 255 else font_size * 0.58
    return max(font_size, int(width))


def build_ass(xml_path: Path, ass_path: Path, width: int, height: int) -> int:
    root = ET.parse(xml_path).getroot()
    events: list[tuple[float, str]] = []
    for node in root.findall("d"):
        raw = node.attrib.get("p", "")
        parts = raw.split(",", 1)
        if len(parts) != 2:
            continue
        try:
            start = float(parts[0])
        except ValueError:
            continue
        text = (node.text or "").strip()
        if text:
            events.append((start, text))
    events.sort(key=lambda item: item[0])

    tracks = 10
    line_height = max(38, int(height * 0.052))
    font_size = max(24, int(height * 0.036))
    top_margin = max(44, int(height * 0.055))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Hiragino Sans GB,{font_size},&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,8,20,20,20,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lane_available = [0.0 for _ in range(tracks)]
    last_start = -1.0
    for start, text in events:
        text_width = estimate_text_width(text, font_size)
        lane = min(range(tracks), key=lambda index: lane_available[index])
        actual_start = max(start, lane_available[lane], last_start + 0.20)
        travel = width + text_width + 48
        speed = max(105.0, width / 17.5)
        duration = min(22.0, max(13.0, travel / speed))
        end = actual_start + duration
        lane_available[lane] = actual_start + 0.35
        last_start = actual_start
        y = top_margin + lane * line_height
        start_x = width + 24
        end_x = -text_width - 24
        effect = rf"{{\an7\move({start_x},{y},{end_x},{y})}}"
        lines.append(
            f"Dialogue: 0,{ass_time(actual_start)},{ass_time(end)},Default,,0,0,0,,{effect}{escape_ass(text)}"
        )
    ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(events)


class DanmakuRenderer:
    def __init__(self, config: AppConfig, runner: ProcessRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger

    def render(
        self,
        source: Path,
        xml_path: Path,
        output_path: Path,
        *,
        quality: str,
        frame_rate: str,
    ) -> int:
        width, height = self.probe_size(source)
        ass_path = output_path.with_suffix(".ass")
        count = build_ass(xml_path, ass_path, width, height)
        if count <= 0:
            ass_path.unlink(missing_ok=True)
            return 0

        fontsdir = "/System/Library/Fonts" if Path("/System/Library/Fonts").is_dir() else ""
        ass_filter = f"ass={ass_path}"
        if fontsdir:
            ass_filter += f":fontsdir={fontsdir}"
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
        filters: list[str] = []
        if quality != "origin":
            height_limit = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality)
            if height_limit:
                filters.append(f"scale=-2:{height_limit}")
        if frame_rate != "source":
            filters.append(f"fps={frame_rate}")
        filters.append(ass_filter)
        command.extend(["-vf", ",".join(filters)])
        bitrate = video_bitrate_kbps(quality, frame_rate)
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
        command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-avoid_negative_ts",
                "make_zero",
                str(output_path),
            ]
        )
        try:
            result = self.runner.run(command)
            if result.returncode != 0 or not output_path.exists():
                raise RuntimeError(f"failed to render danmaku video: {output_path}")
        finally:
            ass_path.unlink(missing_ok=True)
        return count

    def probe_size(self, media: Path) -> tuple[int, int]:
        result = subprocess.run(
            [
                self.config.ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(media),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            width, height = (int(value) for value in result.stdout.strip().split("x", 1))
            return width, height
        except (ValueError, TypeError):
            return 1920, 1080
