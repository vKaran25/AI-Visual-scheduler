"""Timezone conversion with explicit handling of ambiguous/nonexistent wall times."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.domain.time_utils import time_to_minutes


def local_now(zone: str) -> datetime:
    return datetime.now(ZoneInfo(zone))


def wall_instant(day: str, clock: str, zone: str) -> datetime:
    base = datetime.fromisoformat(day) + timedelta(minutes=time_to_minutes(clock))
    tz = ZoneInfo(zone)
    candidates = []
    for fold in (0, 1):
        item = base.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
        if item.astimezone(tz).replace(tzinfo=None) == base and item not in candidates:
            candidates.append(item)
    if not candidates:
        raise ValueError("This local time does not exist because of daylight saving time")
    if len(candidates) > 1:
        raise ValueError(
            "This local time is ambiguous because of daylight saving time; choose a time outside the repeated hour"
        )
    return candidates[0]


def event_instants(day: str, start: str, end: str, zone: str):
    first, last = wall_instant(day, start, zone), wall_instant(day, end, zone)
    if last <= first:
        raise ValueError("Event end must follow its start")
    return first, last
