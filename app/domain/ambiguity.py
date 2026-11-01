"""Conservative coded checks for fixed-event details that must not be guessed."""

import re


def missing_event_details(request: str, answers: list[str]) -> list[str]:
    text = " ".join([request] + answers)
    missing = []
    time = re.search(r"\bat\s+(\d{1,2})(?::\d{2})?\b", request, re.I)
    explicit_period = bool(
        re.search(
            r"(?:\b|(?<=\d))(?:[ap]\.?m\.?)(?!\w)"
            r"|\b(?:morning|afternoon|evening|night|noon|midnight)\b",
            text,
            re.I,
        )
    )
    if time and 1 <= int(time.group(1)) <= 12 and not explicit_period:
        missing.append("AM or PM for the event time")
    duration = bool(
        re.search(
            r"\b(?:\d+(?:\.\d+)?|an?|one|two|three|half)\s*(?:hours?|hrs?|minutes?|mins?|h|m)\b", text, re.I
        )
    )
    time_range = bool(
        re.search(r"\b(?:from|between)\b.+\b(?:to|and)\b|\d\s*(?:am|pm)?\s*[-–]\s*\d", text, re.I)
    )
    if not duration and not time_range:
        missing.append("the event duration")
    return missing
