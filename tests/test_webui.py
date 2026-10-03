from __future__ import annotations

import re
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1] / "src" / "douyin_bili_recorder" / "web"


def _html() -> str:
    return (WEB_ROOT / "index.html").read_text(encoding="utf-8")


def _js() -> str:
    return (WEB_ROOT / "app.js").read_text(encoding="utf-8")


def test_sidebar_exposes_all_required_views() -> None:
    html = _html()
    views = set(re.findall(r'data-view="([a-z]+)"', html))
    assert {"dashboard", "targets", "recording", "bilibili", "cloud", "library", "analytics", "logs"} <= views


def test_recording_and_analytics_panels_exist() -> None:
    html = _html()
    assert 'data-view-panel="recording"' in html
    assert 'data-view-panel="analytics"' in html
    assert 'id="recordingRows"' in html
    assert 'id="analyticsViewMetrics"' in html
    assert 'id="analyticsViewRows"' in html
    assert 'id="analyticsWeekButton"' in html
    assert 'id="analyticsMonthButton"' in html


def test_bilibili_queue_and_submission_status_are_separate_panes() -> None:
    html = _html()
    panes = set(re.findall(r'data-bili-panel="([a-z]+)"', html))
    assert {"queue", "status"} <= panes
    contents = set(re.findall(r'data-bili-panel-content="([a-z]+)"', html))
    assert {"queue", "status"} <= contents


def test_stop_dialog_offers_resume_pause_and_discard() -> None:
    html = _html()
    for element_id in (
        "pauseUploadButton",
        "pauseKeepButton",
        "discardButton",
        "pauseCancelButton",
    ):
        assert f'id="{element_id}"' in html


def test_app_script_wires_new_views() -> None:
    js = _js()
    assert '"recording"' in js and '"analytics"' in js
    assert "function renderRecordingStatus()" in js
    assert "async function openAnalyticsView(" in js
    assert "renderAnalyticsView(" in js


def test_target_cards_show_recording_and_upload_status_separately() -> None:
    js = _js()
    assert "target-status-stack" in js
    assert "recordingStatus" in js
    assert "uploadMeta" in js


def test_layout_uses_fixed_viewport_with_internal_scroll() -> None:
    css = (WEB_ROOT / "app-shell.css").read_text(encoding="utf-8")
    assert ".view-stack" in css
    assert "overflow: hidden" in css
    assert ".app-view[data-view-panel=\"recording\"]" in css
    assert ".app-view[data-view-panel=\"analytics\"]" in css
    assert "scrollbar-gutter: stable" in css
