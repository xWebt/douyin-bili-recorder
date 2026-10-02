from __future__ import annotations

import logging
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import AppConfig
from .process import ProcessRunner

CHINESE_FONT = "Hiragino Sans GB"
EMOJI_FONT = "Noto Emoji"
BUNDLED_FONT_DIR = Path(__file__).with_name("fonts")
DANMAKU_BITRATE_KBPS = {"origin": 24_000, "1080p": 16_000, "720p": 8_000, "480p": 3_000}
RENDER_TIMEOUT_SECONDS = 4 * 60 * 60


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def is_emoji_char(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0x2B00 <= codepoint <= 0x2BFF
        or codepoint in {0x200D, 0x20E3, 0xFE0F}
    )


def format_ass_text(text: str) -> str:
    result: list[str] = []
    in_emoji = False
    for char in text:
        emoji = is_emoji_char(char)
        if emoji != in_emoji:
            result.append(rf"{{\fn{EMOJI_FONT}}}" if emoji else rf"{{\fn{CHINESE_FONT}}}")
            in_emoji = emoji
        result.append(escape_ass(char))
    if in_emoji:
        result.append(rf"{{\fn{CHINESE_FONT}}}")
    return "".join(result)


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
        f"Style: Default,{CHINESE_FONT},{font_size},&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,8,20,20,20,1",
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
            f"Dialogue: 0,{ass_time(actual_start)},{ass_time(end)},Default,,0,0,0,,{effect}{format_ass_text(text)}"
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

        fontsdir = str(BUNDLED_FONT_DIR) if (BUNDLED_FONT_DIR / "NotoEmoji.ttf").is_file() else ""
        ass_filter = f"ass={ass_path}"
        if fontsdir:
            ass_filter += f":fontsdir={fontsdir}"
        filters: list[str] = []
        if quality != "origin":
            edge_limit = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality)
            if edge_limit:
                if width > height:
                    filters.append(f"scale=-2:{edge_limit}")
                else:
                    filters.append(f"scale={edge_limit}:-2")
        if frame_rate != "source":
            filters.append(f"fps={frame_rate}")
        filters.append(ass_filter)

        bitrate = DANMAKU_BITRATE_KBPS.get(quality, DANMAKU_BITRATE_KBPS["origin"])
        if frame_rate == "60":
            bitrate = int(bitrate * 1.35)
        common = [
            self.config.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-fflags",
            "+genpts+igndts",
            "-i",
            str(source),
            "-vf",
            ",".join(filters),
        ]
        container_args = [
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]
        hardware_args = [
            "-c:v",
            "h264_videotoolbox",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-b:v",
            f"{bitrate}k",
            "-maxrate",
            f"{int(bitrate * 1.2)}k",
            "-bufsize",
            f"{bitrate * 2}k",
        ]
        software_args = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-b:v",
            f"{bitrate}k",
            "-maxrate",
            f"{int(bitrate * 1.2)}k",
            "-bufsize",
            f"{bitrate * 2}k",
        ]
        try:
            output_path.unlink(missing_ok=True)
            result = self.runner.run(
                [*common, *hardware_args, *container_args],
                timeout_seconds=RENDER_TIMEOUT_SECONDS,
            )
            if result.cancelled or result.timed_out:
                output_path.unlink(missing_ok=True)
                raise RuntimeError(f"danmaku render interrupted: {output_path}")
            if result.returncode == 0 and output_path.exists():
                return count

            self.logger.warning("hardware danmaku render failed; retrying with libx264")
            output_path.unlink(missing_ok=True)
            result = self.runner.run(
                [*common, *software_args, *container_args],
                timeout_seconds=RENDER_TIMEOUT_SECONDS,
            )
            if result.cancelled or result.timed_out or result.returncode != 0 or not output_path.exists():
                output_path.unlink(missing_ok=True)
                raise RuntimeError(f"failed to render danmaku video: {output_path}")
        finally:
            ass_path.unlink(missing_ok=True)
        return count

    def probe_video_bitrate(self, media: Path) -> int:
        result = subprocess.run(
            [
                self.config.ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=bit_rate",
                "-of",
                "default=nw=1:nk=1",
                str(media),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            return max(0, int(result.stdout.strip()))
        except (TypeError, ValueError):
            return 0

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
