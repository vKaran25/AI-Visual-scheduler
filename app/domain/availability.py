"""Timezone-aware free-time allocation on an absolute minute axis."""

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.domain.intervals import requested_minutes, subtract
from app.domain.time import wall_instant
from app.domain.time_utils import snap_to_5_min, weekday_for_date

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def wall_bounds(day, clock, zone):
    from app.domain.time_utils import time_to_minutes

    naive = datetime.fromisoformat(day) + timedelta(minutes=time_to_minutes(clock))
    tz = ZoneInfo(zone)
    candidates = [naive.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc) for fold in (0, 1)]
    return min(candidates), max(candidates)


def occupied_instants(block, day, zone):
    first, last = block.get("starts_at"), block.get("ends_at")
    if first and last:
        first = datetime.fromisoformat(first) if isinstance(first, str) else first
        last = datetime.fromisoformat(last) if isinstance(last, str) else last
        return first, last
    return wall_bounds(day, block["start"], zone)[0], wall_bounds(day, block["end"], zone)[1]


def allocate(blocks, start_text, hours, zone, max_days=60, until=None):
    tz = ZoneInfo(zone)
    parsed = datetime.fromisoformat(start_text)
    if parsed.tzinfo is None:
        parsed = wall_instant(parsed.date().isoformat(), parsed.strftime("%H:%M"), zone)
    start = snap_to_5_min(parsed.astimezone(timezone.utc)).astimezone(tz)
    total = requested_minutes(hours)
    remaining, allocated = total, []
    for offset in range(max_days):
        day = (start.date() + timedelta(days=offset)).isoformat()
        first = wall_bounds(day, "00:00", zone)[0]
        last = wall_bounds(day, "24:00", zone)[1]
        if until:
            boundary = datetime.fromisoformat(until)
            if boundary.tzinfo is None:
                boundary = wall_instant(boundary.date().isoformat(), boundary.strftime("%H:%M"), zone)
            last = min(last, boundary.astimezone(timezone.utc))
            if first >= last:
                break
        if offset == 0:
            first = max(first, start.astimezone(timezone.utc))
        occupied = []
        for block in blocks:
            repeats = block.get("repeatDays") or []
            if weekday_for_date(day) in repeats if repeats else block.get("date") == day:
                begin, end = occupied_instants(block, day, zone)
                occupied.append(
                    (
                        math.floor((begin - EPOCH).total_seconds() / 60),
                        math.ceil((end - EPOCH).total_seconds() / 60),
                    )
                )
        for begin, end in subtract(
            math.ceil((first - EPOCH).total_seconds() / 60),
            math.floor((last - EPOCH).total_seconds() / 60),
            occupied,
        ):
            begin = math.ceil(begin / 5) * 5
            if end - begin < min(30, total):
                continue
            while begin < end and remaining > 0:
                used = min(end - begin, remaining)
                first_local = (EPOCH + timedelta(minutes=begin)).astimezone(tz)
                last_local = (EPOCH + timedelta(minutes=begin + used)).astimezone(tz)
                start_minutes = first_local.hour * 60 + first_local.minute
                end_minutes = (
                    1440
                    if last_local.date() > first_local.date()
                    else last_local.hour * 60 + last_local.minute
                )
                try:
                    wall_instant(day, first_local.strftime("%H:%M"), zone)
                    wall_instant(day, "24:00" if end_minutes == 1440 else last_local.strftime("%H:%M"), zone)
                    if end_minutes <= start_minutes:
                        raise ValueError("Ambiguous civil interval")
                except ValueError:
                    begin += 5
                    continue
                allocated.append(
                    {
                        "date": day,
                        "start": first_local.strftime("%H:%M"),
                        "end": "24:00" if end_minutes == 1440 else last_local.strftime("%H:%M"),
                        "startMinutes": start_minutes,
                        "endMinutes": end_minutes,
                        "duration": used / 60,
                        "durationStr": f"{used // 60}h {used % 60}m",
                        "starts_at": (EPOCH + timedelta(minutes=begin)).isoformat(),
                        "ends_at": (EPOCH + timedelta(minutes=begin + used)).isoformat(),
                    }
                )
                remaining -= used
                break
        if remaining == 0:
            break
    return {
        "allocated": allocated,
        "totalAllocated": (total - remaining) / 60,
        "requested": hours,
        "fulfilled": remaining == 0,
        "missing": remaining / 60,
    }


def find_gaps(blocks, start_text, end_text, zone):
    tz = ZoneInfo(zone)

    def parse(value):
        parsed = datetime.fromisoformat(value)
        return (
            parsed.astimezone(tz)
            if parsed.tzinfo
            else wall_instant(parsed.date().isoformat(), parsed.strftime("%H:%M"), zone).astimezone(tz)
        )

    start, end = parse(start_text), parse(end_text)
    if end <= start or (end - start).days > 60:
        raise ValueError("Choose an availability range of up to 60 days")
    result = []
    for offset in range((end.date() - start.date()).days + 1):
        day = (start.date() + timedelta(days=offset)).isoformat()
        first = max(start.astimezone(timezone.utc), wall_bounds(day, "00:00", zone)[0])
        last = min(end.astimezone(timezone.utc), wall_bounds(day, "24:00", zone)[1])
        if last <= first:
            continue
        occupied = []
        for block in blocks:
            repeats = block.get("repeatDays") or []
            if weekday_for_date(day) in repeats if repeats else block.get("date") == day:
                begin, finish = occupied_instants(block, day, zone)
                occupied.append(
                    (
                        math.floor((begin - EPOCH).total_seconds() / 60),
                        math.ceil((finish - EPOCH).total_seconds() / 60),
                    )
                )
        for begin, finish in subtract(
            math.ceil((first - EPOCH).total_seconds() / 60),
            math.floor((last - EPOCH).total_seconds() / 60),
            occupied,
        ):
            a, b = (
                (EPOCH + timedelta(minutes=begin)).astimezone(tz),
                (EPOCH + timedelta(minutes=finish)).astimezone(tz),
            )
            result.append(
                {
                    "date": day,
                    "start": a.strftime("%H:%M"),
                    "end": "24:00" if b.date() > a.date() else b.strftime("%H:%M"),
                    "starts_at": a.isoformat(),
                    "ends_at": b.isoformat(),
                    "duration": (finish - begin) / 60,
                }
            )
    return result
