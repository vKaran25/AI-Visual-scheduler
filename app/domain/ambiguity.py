"""Conservative coded checks for fixed-event details that must not be guessed.

Only a genuinely ambiguous clock time (no AM/PM) is asked about. A missing length or date is filled
from category defaults (app.domain.categories) and shown in the draft for the student to approve.
"""

import re

_HOURS = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"


def has_duration(text: str) -> bool:
    # "9 am" must not count as a length, so single letters only follow digits ("45m", "2h").
    length = re.search(
        r"\b(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?|h|m)"
        r"|(?:an?|one|two|three|four|fifteen|twenty|thirty|forty|forty-five|sixty|ninety)\s+(?:hours?|hrs?|minutes?|mins?))\b",
        text,
        re.I,
    )
    time_range = re.search(
        r"\b(?:from|between)\b.+\b(?:to|and|until|till)\b|\d\s*(?:am|pm)?\s*[-–]\s*\d|\b(?:until|till)\b",
        text,
        re.I,
    )
    return bool(length or time_range)


def missing_event_details(request: str, answers: list[str]) -> list[str]:
    text = " ".join([request] + answers)
    missing = []
    time = re.search(rf"\bat\s+(\d{{1,2}}|{_HOURS})(?::\d{{2}})?\b", request, re.I)
    explicit_period = bool(
        re.search(
            r"(?:\b|(?<=\d))(?:[ap]\.?m\.?)(?!\w)"
            r"|\b(?:morning|afternoon|evening|night|tonight|noon|midnight|breakfast|lunch|dinner)\b",
            text,
            re.I,
        )
    )
    if time and not explicit_period:
        hour = time.group(1)
        if not hour.isdigit() or 1 <= int(hour) <= 12:
            missing.append("AM or PM for the event time")
    return missing
