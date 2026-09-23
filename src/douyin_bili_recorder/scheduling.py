from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import ScheduleSlot


def parse_hhmm(value: str) -> time:
    hour, minute = value.strip().split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def slot_start_for_moment(slot: ScheduleSlot, moment: datetime) -> datetime:
    start = parse_hhmm(slot.start)
    end = parse_hhmm(slot.end)
    start_at = moment.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    end_at = moment.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if end_at <= start_at:
        end_at += timedelta(days=1)
    if moment < start_at and moment <= end_at - timedelta(days=1):
        start_at -= timedelta(days=1)
    return start_at


def slot_contains(slot: ScheduleSlot, moment: datetime) -> bool:
    if not slot.enabled or not slot.days:
        return False
    start_time = parse_hhmm(slot.start)
    end_time = parse_hhmm(slot.end)
    start_at = moment.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
    end_at = moment.replace(hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0)
    scheduled_date = moment.date()
    if end_at <= start_at:
        end_at += timedelta(days=1)
        if moment < start_at:
            scheduled_date -= timedelta(days=1)
            start_at -= timedelta(days=1)
            end_at -= timedelta(days=1)
    if scheduled_date.isoweekday() not in slot.days:
        return False
    return start_at <= moment <= end_at


def active_slot(slots: list[ScheduleSlot], moment: datetime) -> ScheduleSlot | None:
    return next((slot for slot in slots if slot_contains(slot, moment)), None)


def expected_start_for_moment(slot: ScheduleSlot, moment: datetime) -> datetime:
    return slot_start_for_moment(slot, moment)


def is_late_detection(
    detected_at: datetime,
    scheduled_start: datetime | None,
    threshold_minutes: int,
) -> tuple[bool, int]:
    if scheduled_start is None:
        return False, 0
    delta_minutes = int((detected_at - scheduled_start).total_seconds() // 60)
    if delta_minutes <= threshold_minutes:
        return False, max(0, delta_minutes)
    return True, max(0, delta_minutes)


def should_poll_now(
    slots: list[ScheduleSlot],
    moment: datetime,
    *,
    precheck_minutes: int = 10,
) -> bool:
    if not slots:
        return True
    for slot in slots:
        if not slot.enabled or not slot.days:
            continue
        if slot_contains(slot, moment):
            return True
        start_time = parse_hhmm(slot.start)
        start_at = moment.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
        for day_offset in (0, 1):
            candidate_date = moment.date() + timedelta(days=day_offset)
            if candidate_date.isoweekday() not in slot.days:
                continue
            candidate = datetime.combine(candidate_date, start_time)
            if timedelta(0) <= candidate - moment <= timedelta(minutes=precheck_minutes):
                return True
    return False


def next_poll_delay_seconds(
    slots: list[ScheduleSlot],
    moment: datetime,
    *,
    inside_seconds: int = 120,
    outside_seconds: int = 900,
) -> int:
    return inside_seconds if should_poll_now(slots, moment) else outside_seconds
