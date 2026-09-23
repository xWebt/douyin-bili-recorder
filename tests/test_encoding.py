from douyin_bili_recorder.encoding import estimate_gb_per_hour, needs_transcode, peak_gb_per_segment, video_bitrate_kbps


def test_origin_source_uses_direct_source_path() -> None:
    assert needs_transcode("origin", "source") is False
    assert estimate_gb_per_hour("origin", "source") == 8.4


def test_transcode_profiles_have_lower_hourly_estimates() -> None:
    assert needs_transcode("720p", "30") is True
    assert estimate_gb_per_hour("720p", "30") < 2
    assert estimate_gb_per_hour("480p", "30") < 1


def test_60fps_estimate_is_higher_than_30fps() -> None:
    assert video_bitrate_kbps("1080p", "60") > video_bitrate_kbps("1080p", "30")
    assert estimate_gb_per_hour("1080p", "60") > estimate_gb_per_hour("1080p", "30")


def test_transcode_peak_includes_original_plus_output() -> None:
    output = estimate_gb_per_hour("720p", "30")
    peak = peak_gb_per_segment("720p", "30")
    assert peak > 8.4 + output
