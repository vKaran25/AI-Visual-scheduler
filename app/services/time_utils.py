import re
from datetime import date, datetime, timedelta

MIN_FREE_BLOCK_MINUTES = 30
MAX_SEARCH_DAYS = 60


def snap_to_30_min(dt: datetime) -> datetime:
    if dt.second or dt.microsecond:
        dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if dt.minute in (0, 30):
        return dt
    if dt.minute < 30:
        return dt.replace(minute=30)
    return (dt + timedelta(hours=1)).replace(minute=0)


def snap_to_5_min(dt: datetime) -> datetime:
    """Round up to the next five-minute boundary, never into the past."""
    if dt.second or dt.microsecond:
        dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    remainder = dt.minute % 5
    return dt + timedelta(minutes=(5 - remainder) % 5)


def time_to_minutes(t: str) -> int:
    if not isinstance(t, str) or not re.fullmatch(r"\d{2}:\d{2}", t):
        raise ValueError("Invalid time format (expected HH:MM)")
    h, m = map(int, t.split(":"))
    if m >= 60 or h > 24 or (h == 24 and m != 0):
        raise ValueError("Time must be between 00:00 and 24:00")
    return h * 60 + m


def validate_calendar_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Date must be in YYYY-MM-DD format")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid calendar date") from exc
    return value


def minutes_to_time(mins: int) -> str:
    if mins <= 0:
        return "00:00"
    if mins >= 1440:
        return "24:00"
    return f"{mins // 60:02d}:{mins % 60:02d}"


def normalize_repeat_days(days):
    if not days:
        return []
    normalized = set()
    for day in days:
        try:
            value = int(day)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 6:
            normalized.add(value)
    return sorted(normalized)


def parse_positive_float(value, default=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_time_range(start, end):
    if not start or not end:
        raise ValueError("Start and end are required")
    try:
        start_minutes = time_to_minutes(start)
        end_minutes = time_to_minutes(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid time format") from exc
    if end_minutes <= start_minutes:
        raise ValueError("End must be after start")
    return start_minutes, end_minutes


def weekday_for_date(date_str: str) -> int:
    return datetime.strptime(date_str, "%Y-%m-%d").weekday()

