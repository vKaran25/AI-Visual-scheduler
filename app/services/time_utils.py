from datetime import datetime

MIN_FREE_BLOCK_MINUTES = 30
MAX_SEARCH_DAYS = 60


def time_to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


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

