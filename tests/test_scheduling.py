from __future__ import annotations

from datetime import datetime

from douyin_bili_recorder.models import ScheduleSlot
from douyin_bili_recorder.scheduling import active_slot, is_late_detection, should_poll_now, slot_contains


def test_normal_schedule_window() -> None:
    slot = ScheduleSlot(days=[1], start="20:00", end="23:00")
    monday = datetime(2026, 9, 21, 20, 4)
    assert slot_contains(slot, monday)
    assert active_slot([slot], monday) is slot
    assert should_poll_now([slot], monday)


def test_overnight_schedule_window() -> None:
    slot = ScheduleSlot(days=[1], start="23:30", end="02:00")
    tuesday = datetime(2026, 9, 22, 1, 0)
    assert slot_contains(slot, tuesday)


def test_five_minute_late_threshold() -> None:
    slot = ScheduleSlot(days=[1], start="20:00", end="23:00")
    scheduled = datetime(2026, 9, 21, 20, 0)
    on_time, minutes = is_late_detection(datetime(2026, 9, 21, 20, 5), scheduled, 5)
    late, late_minutes = is_late_detection(datetime(2026, 9, 21, 20, 6), scheduled, 5)
    assert on_time is False
    assert minutes == 5
    assert late is True
    assert late_minutes == 6
