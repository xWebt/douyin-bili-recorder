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


def test_new_targets_default_to_all_day_without_schedule() -> None:
    js = _js()
    assert js.count('watch_mode: "all_day"') >= 2
    assert js.count("schedule: []") >= 2


def test_storage_and_encoder_controls_exist() -> None:
    html = _html()
    for element_id in (
        "cacheFullPolicy",
        "failedRetentionDays",
        "keepOriginalFiles",
        "quarkSyncDir",
        "quarkSyncRemoteRoot",
        "danmakuEncoder",
    ):
        assert f'id="{element_id}"' in html


def test_quark_official_client_test_controls_exist() -> None:
    html = _html()
    css = (WEB_ROOT / "redesign.css").read_text(encoding="utf-8")
    assert 'id="quarkTestButton"' in html
    assert 'id="quarkOpenButton"' in html
    assert "夸克电脑备份目录" in html
    assert ".quark-test-actions" in css


def test_recording_and_analytics_helpers_stay_top_level() -> None:
    js = _js()
    start = js.index("async function openAnalytics(name)")
    next_helper = js.index("function recordingStateMeta(session)", start)
    open_analytics = js[start:next_helper]
    assert open_analytics.count("{") == open_analytics.count("}")
    assert "function renderRecordingStatus()" in js[next_helper:]
    assert "async function openAnalyticsView(" in js[next_helper:]


def test_schedule_editor_is_visible_and_has_visible_add_action() -> None:
    js = _js()
    css = (WEB_ROOT / "redesign.css").read_text(encoding="utf-8")
    assert "schedule-editor-heading" in js
    assert "添加时段" in js
    assert "details" not in js[js.index("if (target.watch_mode === \"scheduled\")") : js.index("function buildScheduleList", js.index("if (target.watch_mode === \"scheduled\")"))]
    assert ".schedule-editor-heading" in css


def test_target_add_has_duplicate_guard_and_request_lock() -> None:
    js = _js()
    assert "targetSubmitPending" in js
    assert "targetIdentity" in js
    assert "已经在监控列表中" in js
    assert "未添加主播" in js


def test_toast_notifications_are_prominent_and_accessible() -> None:
    js = _js()
    css = (WEB_ROOT / "redesign.css").read_text(encoding="utf-8")
    assert 'node.setAttribute("role", type === "error" ? "alert" : "status")' in js
    assert "toast-copy" in js
    assert "toast.error > i" in css
    assert "top: 18px" in css
