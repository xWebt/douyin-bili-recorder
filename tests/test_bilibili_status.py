from __future__ import annotations

from douyin_bili_recorder.bilibili_status import BilibiliSubmissionClient


def test_parse_archive_uses_real_state_description() -> None:
    status = BilibiliSubmissionClient._parse_archive(
        {
            "bvid": "BV0000000001",
            "title": "主播｜直播录像",
            "state": "is_pubing",
            "primary_state": "is_pubing",
            "state_desc": "审核中",
            "duration": 3600,
        }
    )

    assert status is not None
    assert status.bvid == "BV0000000001"
    assert status.state_desc == "审核中"
    assert status.duration_seconds == 3600


def test_parse_archive_maps_primary_state_without_fake_percentage() -> None:
    status = BilibiliSubmissionClient._parse_archive(
        {
            "bvid": "BV0000000002",
            "title": "主播｜直播录像",
            "primary_state": "pubed",
            "duration": 120,
        }
    )

    assert status is not None
    assert status.state_desc == "已发布"
    assert "%" not in status.state_desc
