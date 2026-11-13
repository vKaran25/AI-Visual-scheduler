"""Calendar operations for external AI clients (the MCP server) and scripts.

Every function takes an open database session and the owning user, and reuses the same
validation, overlap checks and per-user locking as the web application.

`propose_event` never writes anything. `create_event` saves immediately, so an AI client should
only call it after the user has agreed to the proposal.
"""

import re
from datetime import datetime, timedelta

from app.domain.contracts import Action, EventData
from app.domain.time import local_now
from app.domain.time_utils import snap_to_30_min, validate_calendar_date, validate_time_range
from app.services import draft_service, scheduler_service

MAX_RANGE_DAYS = 42
DEFAULT_COLOR = "#397969"


def parse_clock(value: str) -> str:
    """Accept '16:00', '4pm', '4:30 PM' and return zero-padded 24-hour 'HH:MM'."""
    text = str(value or "").strip().lower().replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not match:
        raise ValueError(f"Could not understand the time '{value}'. Use 24-hour HH:MM such as 16:30.")
    hour, minute, period = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if period:
        if not 1 <= hour <= 12:
            raise ValueError(f"'{value}' is not a valid 12-hour time")
        hour = hour % 12 + (12 if period == "pm" else 0)
    if hour > 24 or minute > 59 or (hour == 24 and minute):
        raise ValueError(f"'{value}' is not a valid time")
    return f"{hour:02d}:{minute:02d}"


def _event_payload(title, date, start, end, color):
    return {
        "date": validate_calendar_date(date),
        "start": parse_clock(start),
        "end": parse_clock(end),
        "label": (title or "Busy").strip()[:240] or "Busy",
        "color": color or DEFAULT_COLOR,
        "repeatDays": [],
    }


def _summary(event):
    return f"{event['label']} on {event['date']} from {event['start']} to {event['end']}"


def list_events(db, user, start_date: str, end_date: str) -> dict:
    """Events (including weekly ones expanded per day and unapproved assistant proposals)."""
    first = datetime.strptime(validate_calendar_date(start_date), "%Y-%m-%d").date()
    last = datetime.strptime(validate_calendar_date(end_date), "%Y-%m-%d").date()
    if not 0 <= (last - first).days < MAX_RANGE_DAYS:
        raise ValueError(f"Choose a range of 1 to {MAX_RANGE_DAYS} days")
    blocks = scheduler_service.user_blocks(db, user.id)
    days = {}
    for offset in range((last - first).days + 1):
        day = (first + timedelta(days=offset)).isoformat()
        events = [
            scheduler_service.block_to_dict(b, display_date=day)
            for b in blocks
            if scheduler_service.slot_applies_to_date(b, day)
        ] + draft_service.overlays(db, user, day)
        days[day] = sorted(
            (
                {
                    "id": e["id"],
                    "title": e["label"],
                    "start": e["start"],
                    "end": e["end"],
                    "minutes": e.get("durationMinutes") or (e["endMinutes"] - e["startMinutes"]),
                    "repeats_weekly": bool(e["repeatDays"]),
                    "status": "proposed (not saved)" if e.get("is_pending") else "confirmed",
                }
                for e in events
            ),
            key=lambda e: e["start"],
        )
    return {"timezone": user.timezone, "days": days}


def find_free_time(db, user, hours: float, from_datetime: str | None = None) -> dict:
    """Earliest free slots totalling `hours`, starting now or at `from_datetime` (ISO local time)."""
    start = from_datetime or snap_to_30_min(local_now(user.timezone).replace(tzinfo=None)).isoformat(
        timespec="minutes"
    )
    result = scheduler_service.compute_free_blocks(db, user, start, float(hours))
    return {"timezone": user.timezone, "starting_from": start, **result}


def propose_event(db, user, title: str, date: str, start: str, end: str, color: str | None = None) -> dict:
    """Check an event against the calendar and describe it. Saves nothing."""
    try:
        event = _event_payload(title, date, start, end, color)
        prepared = draft_service.prepare(db, user, [Action(kind="create", event=EventData(**event))])
    except ValueError as exc:
        message = str(exc)
        result = {"valid": False, "saved": False, "problem": message}
        if "overlap" in message.lower():
            try:
                first, last = validate_time_range(parse_clock(start), parse_clock(end))
                slots = find_free_time(
                    db, user, (last - first) / 60, f"{validate_calendar_date(date)}T08:00"
                ).get("allocated", [])[:3]
                result["alternatives"] = [
                    {"date": s["date"], "start": s["start"], "end": s["end"]} for s in slots
                ]
            except ValueError:
                pass
        return result
    change = prepared["preview"]["changes"][0]["event"]
    return {
        "valid": True,
        "saved": False,
        "summary": _summary(event),
        "minutes": round(change["durationMinutes"]),
        "timezone": user.timezone,
        "next_step": "Nothing is saved yet. If the user agrees, call create_event with the same details.",
        "event": event,
    }


def create_event(db, user, title: str, date: str, start: str, end: str, color: str | None = None) -> dict:
    """Save an event to the calendar (rejects overlaps and invalid times)."""
    event = _event_payload(title, date, start, end, color)
    EventData(**event)  # same contract the assistant's drafts must satisfy
    block = scheduler_service.create_block(db, user, event)
    return {"saved": True, "id": block.id, "summary": _summary(event), "timezone": user.timezone}
