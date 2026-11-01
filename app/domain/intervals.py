"""Deterministic interval arithmetic, independent of persistence and models."""

import math


def merge(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def subtract(start: int, end: int, occupied):
    cursor = start
    result = []
    for first, last in merge(occupied):
        if last <= cursor:
            continue
        if first >= end:
            break
        if first > cursor:
            result.append((cursor, min(first, end)))
        cursor = max(cursor, last)
    if cursor < end:
        result.append((cursor, end))
    return result


def requested_minutes(hours: float) -> int:
    if isinstance(hours, bool) or not math.isfinite(hours) or hours <= 0 or hours > 1440:
        raise ValueError("hours must be finite, positive, and at most 1440")
    return math.ceil(hours * 60 - 1e-9)
