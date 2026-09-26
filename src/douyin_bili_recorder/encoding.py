from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EncodingProfile:
    key: str
    label: str
    video_bitrate_kbps: int
    height: int | None


QUALITY_PROFILES: dict[str, EncodingProfile] = {
    "origin": EncodingProfile("origin", "原画", 0, None),
    "1080p": EncodingProfile("1080p", "1080P", 5500, 1080),
    "720p": EncodingProfile("720p", "720P", 3500, 720),
    "480p": EncodingProfile("480p", "480P", 1500, 480),
}

FRAME_RATES = {"source", "60", "30"}
DEFAULT_ORIGIN_GB_PER_HOUR = 8.4


def needs_transcode(quality: str, frame_rate: str) -> bool:
    return quality != "origin" or frame_rate != "source"


def video_bitrate_kbps(quality: str, frame_rate: str) -> int:
    profile = QUALITY_PROFILES.get(quality, QUALITY_PROFILES["origin"])
    bitrate = profile.video_bitrate_kbps
    if not bitrate:
        return 0
    if frame_rate == "60":
        bitrate = int(bitrate * 1.45)
    elif frame_rate == "30" and quality == "1080p":
        bitrate = int(bitrate * 0.9)
    return bitrate


def peak_gb_per_segment(
    quality: str,
    frame_rate: str,
    *,
    segment_seconds: int = 3600,
    origin_rate_gb_per_hour: float = DEFAULT_ORIGIN_GB_PER_HOUR,
    burn_danmaku: bool = False,
) -> float:
    output = estimate_gb_per_hour(
        quality,
        frame_rate,
        segment_seconds=segment_seconds,
        origin_rate_gb_per_hour=origin_rate_gb_per_hour,
    )
    if needs_transcode(quality, frame_rate) or burn_danmaku:
        source = origin_rate_gb_per_hour * segment_seconds / 3600
        return round((source + output) * 1.08, 2)
    return round(output * 1.1, 2)


def estimate_gb_per_hour(
    quality: str,
    frame_rate: str,
    *,
    segment_seconds: int = 3600,
    origin_rate_gb_per_hour: float = DEFAULT_ORIGIN_GB_PER_HOUR,
) -> float:
    if not needs_transcode(quality, frame_rate):
        return round(origin_rate_gb_per_hour, 2)
    if quality == "origin":
        factor = 1.2 if frame_rate == "60" else 0.9
        return round(origin_rate_gb_per_hour * factor, 2)
    video_kbps = video_bitrate_kbps(quality, frame_rate)
    audio_kbps = 128
    estimated = (video_kbps + audio_kbps) * segment_seconds / 8 / 1024 / 1024
    return round(estimated * 1.05, 2)
