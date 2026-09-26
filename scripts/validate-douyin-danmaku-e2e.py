from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from douyin_bili_recorder.config import load_config
from douyin_bili_recorder.models import SessionPart, SessionRecord
from douyin_bili_recorder.process import ProcessRunner
from douyin_bili_recorder.recorder import BiliupRecorder
from douyin_bili_recorder.uploader import BiliupUploader


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


def probe_size(ffprobe: Path, media: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            str(ffprobe),
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
    for start, text in events:
        text_width = estimate_text_width(text, font_size)
        duration = min(11.0, max(7.0, 6.5 + text_width / max(1, width) * 2.5))
        end = start + duration
        lane = min(range(tracks), key=lambda index: lane_available[index])
        lane_available[lane] = end
        y = top_margin + lane * line_height
        start_x = width + 24
        end_x = -text_width - 24
        effect = (
            rf"{{\an7\move({start_x},{y},{end_x},{y})}}"
        )
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{effect}{escape_ass(text)}"
        )
    ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(events)


def run(args: argparse.Namespace) -> int:
    root = Path(tempfile.mkdtemp(prefix="dbr-danmaku-e2e-", dir="/private/tmp"))
    config_path = root / "config.toml"
    config_path.write_text(
        f"""
[app]
data_dir = {str(root / 'data')!r}

[recording]
segment_time = "{args.segment}s"
quality = "origin"
frame_rate = "source"
min_file_size_mb = 0
keep_original_files = true

[storage]
video_dir = {str(root / 'videos')!r}
max_cache_gb = 10

[upload]
biliup_bin = "__INTERNAL_BILIUP__"
ffmpeg_bin = {str(args.ffmpeg)!r}
ffprobe_bin = {str(args.ffprobe)!r}
cookie_file = {str(args.cookie)!r}
line = "bda2"
public = false
delete_after_upload = false
retry_count = 0
retry_backoff_seconds = 1

[[targets]]
name = {args.name!r}
url = {args.url!r}
public = false
record_mode = "record"
record_danmaku = true
watch_mode = "manual"
title_template = "{{name}}｜{{start_date}} {{start_time}} 开播｜{{room_title}}"
tags = ["直播录像", "抖音", "弹幕验证"]
tid = 171
copyright = 2
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    target = config.targets[0]
    session_id = f"{datetime.now():%Y%m%d-%H%M%S}-danmaku-e2e"
    session_dir = config.sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("danmaku-e2e")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    runner = ProcessRunner(logger, threading.Event())
    recorder = BiliupRecorder(config, runner, logger)
    process = recorder.start(target, session_dir)
    time.sleep(args.duration)
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)

    runtime = session_dir / ".danmaku-runtime"
    media_files = sorted(
        [
            path
            for path in runtime.glob("*")
            if path.suffix.lower() in {".flv", ".ts", ".mp4"} and path.stat().st_size > 0
        ],
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    if not media_files:
        raise RuntimeError("no complete media file was produced")
    media = media_files[0]
    xml_path = media.with_suffix(".xml")
    if not xml_path.exists():
        candidates = sorted(runtime.glob("*.xml"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError("no danmaku XML was produced")
        xml_path = candidates[0]

    width, height = probe_size(args.ffprobe, media)
    ass_path = session_dir / "danmaku.ass"
    danmaku_count = build_ass(xml_path, ass_path, width, height)
    if danmaku_count <= 0:
        raise RuntimeError("danmaku XML contained no <d> messages")

    burned = session_dir / "danmaku-burned.mp4"
    command = [
        str(args.ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(media),
        "-vf",
        f"ass={ass_path}:fontsdir=/System/Library/Fonts",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(burned),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0 or not burned.exists():
        raise RuntimeError("failed to burn danmaku into video")

    print(f"MEDIA={media}")
    print(f"XML={xml_path}")
    print(f"BURNED={burned}")
    print(f"DANMAKU_COUNT={danmaku_count}")
    if not args.upload:
        return 0

    session = SessionRecord(
        session_id=session_id,
        target_name=target.name,
        target_url=target.url,
        detected_start_epoch=int(time.time()),
        detected_start_iso=datetime.now().astimezone().isoformat(timespec="seconds"),
        title=args.title,
        parts=[
            SessionPart(
                index=1,
                status="PENDING",
                title=args.title,
                path=str(burned),
                source_path=str(media),
                size=burned.stat().st_size,
            )
        ],
    )
    uploader = BiliupUploader(config, runner, logger)
    result = uploader.upload_part(target, session, burned, part_index=1, title=args.title)
    print(f"BVID={result.bvid}")
    print(f"VERIFIED={result.verified}")
    return 0 if result.verified and result.bvid else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", default="抖音弹幕验证")
    parser.add_argument("--duration", type=float, default=36)
    parser.add_argument("--segment", type=int, default=30)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--title", default="")
    parser.add_argument(
        "--cookie",
        type=Path,
        default=Path.home() / "Library/Application Support/DouyinBiliRecorder/cookies.json",
    )
    parser.add_argument(
        "--ffmpeg",
        type=Path,
        default=Path("/Users/webt/Applications/DouyinBiliRecorder.app/Contents/Resources/runtime/_internal/bin/ffmpeg"),
    )
    parser.add_argument(
        "--ffprobe",
        type=Path,
        default=Path("/Users/webt/Applications/DouyinBiliRecorder.app/Contents/Resources/runtime/_internal/bin/ffprobe"),
    )
    args = parser.parse_args()
    args.title = args.title or f"{args.name}｜抖音弹幕录制验证｜{datetime.now():%Y-%m-%d %H:%M}"
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
