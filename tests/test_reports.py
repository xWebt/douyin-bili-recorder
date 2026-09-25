from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from douyin_bili_recorder.paths import analytics_dir
from douyin_bili_recorder.reports import ReportGenerator


def test_generate_monthly_pdf_report(tmp_path: Path) -> None:
    target_name = "测试主播"
    data_dir = analytics_dir(tmp_path, target_name)
    data_dir.mkdir(parents=True)
    records = [
        {
            "session_id": "s1",
            "date": "2026-09-22",
            "detected_start_iso": "2026-09-22T20:01:00+08:00",
            "duration_seconds": 7200,
            "late": False,
            "late_minutes": 1,
            "reconnect_count": 0,
            "bvid": "BV0000000001",
            "status": "UPLOADED",
        },
        {
            "session_id": "s2",
            "date": "2026-09-24",
            "detected_start_iso": "2026-09-24T20:12:00+08:00",
            "duration_seconds": 5400,
            "late": True,
            "late_minutes": 12,
            "reconnect_count": 1,
            "bvid": "BV0000000002",
            "status": "UPLOADED",
        },
    ]
    (data_dir / "2026-09.json").write_text(
        json.dumps({"version": 1, "month": "2026-09", "target_name": target_name, "sessions": records}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = ReportGenerator(tmp_path).generate(target_name, "month", anchor_date=date(2026, 9, 25))

    assert report.exists()
    assert report.name == "测试主播_月报_202609.pdf"
    assert report.read_bytes().startswith(b"%PDF-")


def test_generate_weekly_pdf_report_spans_month_boundaries(tmp_path: Path) -> None:
    target_name = "跨月主播"
    data_dir = analytics_dir(tmp_path, target_name)
    data_dir.mkdir(parents=True)
    for month, session_id, day in (("2026-08", "a", "31"), ("2026-09", "b", "01")):
        (data_dir / f"{month}.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "month": month,
                    "target_name": target_name,
                    "sessions": [
                        {
                            "session_id": session_id,
                            "date": f"{month}-{day}",
                            "detected_start_iso": f"{month}-{day}T20:00:00+08:00",
                            "duration_seconds": 3600,
                            "parts": 1,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    report = ReportGenerator(tmp_path).generate(target_name, "week", anchor_date=date(2026, 9, 2))

    assert report.exists()
    assert report.name == "跨月主播_周报_20260831_20260906.pdf"
