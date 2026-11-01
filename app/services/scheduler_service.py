"""Calendar commands and read models. All mutations share a user row lock."""

import json
import re
from datetime import datetime

from sqlmodel import select

from app.db.models import Block
from app.db.transactions import changed, lock_calendar
from app.domain.time import event_instants
from app.domain.time_utils import (
    MAX_SEARCH_DAYS,
    normalize_repeat_days,
    validate_calendar_date,
    validate_time_range,
    weekday_for_date,
)
from app.services import outbox


def block_to_dict(block, display_date=None):
    return {
        "id": block.id,
        "date": display_date if display_date is not None else block.date,
        "start": block.start,
        "end": block.end,
        "startMinutes": block.start_minutes,
        "endMinutes": block.end_minutes,
        "label": block.label,
        "color": block.color,
        "repeatDays": json.loads(block.repeat_days_json or "[]"),
        "is_gcal": block.is_gcal,
        "is_default": block.is_default,
        "is_pending": block.is_pending,
        "session_id": block.session_id,
        "preset_source": block.preset_source,
        "revision": block.revision,
        "timezone": block.timezone,
        "durationMinutes": round((block.ends_at - block.starts_at).total_seconds() / 60)
        if block.starts_at and block.ends_at
        else block.end_minutes - block.start_minutes,
    }


def user_blocks(session, user_id):
    return list(session.exec(select(Block).where(Block.user_id == user_id, Block.is_pending == False)).all())


def slot_applies_to_date(block, date_str):
    repeats = json.loads(block.repeat_days_json or "[]")
    return weekday_for_date(date_str) in repeats if repeats else block.date == date_str


def slots_for_date(session, user, date_str):
    return [
        block_to_dict(b, date_str) for b in user_blocks(session, user.id) if slot_applies_to_date(b, date_str)
    ]


def slot_overlaps(session, user_id, start_minutes, end_minutes, date_str, repeat_days=None, ignore_id=None):
    repeats = normalize_repeat_days(repeat_days or [])
    for block in user_blocks(session, user_id):
        if block.id == ignore_id or start_minutes >= block.end_minutes or end_minutes <= block.start_minutes:
            continue
        existing = json.loads(block.repeat_days_json or "[]")
        if repeats:
            if (existing and set(existing) & set(repeats)) or (
                not existing and block.date and weekday_for_date(block.date) in repeats
            ):
                return block
        elif date_str and slot_applies_to_date(block, date_str):
            return block
    return None


def validate_no_overlap(
    session, user_id, start_minutes, end_minutes, date_str, repeat_days=None, ignore_id=None
):
    if not date_str and not repeat_days:
        raise ValueError("Date or repeat days are required")
    conflict = slot_overlaps(session, user_id, start_minutes, end_minutes, date_str, repeat_days, ignore_id)
    if conflict:
        raise ValueError(f"Time overlaps with existing block: {conflict.label}")


def create_block(
    session,
    user,
    data,
    *,
    is_default=False,
    is_pending=False,
    session_id=None,
    preset_source=None,
    skip_overlap=False,
    commit=True,
):
    if is_pending:
        raise ValueError("Unapproved events belong in Draft, not the calendar")
    owner = lock_calendar(session, user.id)
    if not re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{5})?", data.get("color", "#d81b60")):
        raise ValueError("Choose a hexadecimal event color")
    first, last = validate_time_range(data.get("start"), data.get("end"))
    repeats = normalize_repeat_days(data.get("repeatDays", []))
    day = None if repeats else validate_calendar_date(data.get("date"))
    if not skip_overlap:
        validate_no_overlap(session, user.id, first, last, day, repeats)
    if repeats:
        first_at, last_at = None, None
    elif data.get("is_gcal") and data.get("starts_at") and data.get("ends_at"):
        first_at, last_at = datetime.fromisoformat(data["starts_at"]), datetime.fromisoformat(data["ends_at"])
    else:
        first_at, last_at = event_instants(day, data["start"], data["end"], owner.timezone)
    block = Block(
        user_id=user.id,
        date=day,
        start=data["start"],
        end=data["end"],
        start_minutes=first,
        end_minutes=last,
        starts_at=first_at,
        ends_at=last_at,
        timezone=owner.timezone,
        label=str(data.get("label") or "Busy")[:240],
        color=data.get("color", "#d81b60"),
        repeat_days_json=json.dumps(repeats),
        is_gcal=bool(data.get("is_gcal", False)),
        is_default=is_default,
        session_id=session_id,
        preset_source=preset_source,
    )
    session.add(block)
    session.flush()
    changed(session, owner)
    outbox.enqueue(session, block, "upsert")
    if commit:
        session.commit()
        session.refresh(block)
    return block


def update_block(session, user, block_id, data, *, commit=True, skip_overlap=False):
    owner = lock_calendar(session, user.id)
    block = session.exec(
        select(Block)
        .where(Block.id == block_id, Block.user_id == user.id)
        .execution_options(populate_existing=True)
    ).first()
    if not block:
        return None
    if block.is_gcal:
        raise ValueError("Imported Google events are read-only")
    if data.get("revision") is not None and data["revision"] != block.revision:
        raise ValueError("This event changed; reload before editing")
    start, end = data.get("start", block.start), data.get("end", block.end)
    first, last = validate_time_range(start, end)
    repeats = normalize_repeat_days(data.get("repeatDays", json.loads(block.repeat_days_json)))
    day = None if repeats else validate_calendar_date(data.get("date", block.date))
    if not skip_overlap:
        validate_no_overlap(session, user.id, first, last, day, repeats, ignore_id=block_id)
    block.date, block.start, block.end = day, start, end
    block.start_minutes, block.end_minutes = first, last
    block.repeat_days_json = json.dumps(repeats)
    color = data.get("color", block.color)
    if not isinstance(color, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{5})?", color
    ):
        raise ValueError("Choose a hexadecimal event color")
    block.label, block.color = str(data.get("label", block.label))[:240], color
    block.starts_at, block.ends_at = (
        (None, None) if repeats else event_instants(day, start, end, owner.timezone)
    )
    block.timezone = owner.timezone
    block.revision += 1
    session.add(block)
    changed(session, owner)
    outbox.enqueue(session, block, "upsert")
    if commit:
        session.commit()
        session.refresh(block)
    return block


def delete_block(session, user, block_id, *, commit=True, expected_revision=None):
    owner = lock_calendar(session, user.id)
    block = session.exec(
        select(Block)
        .where(Block.id == block_id, Block.user_id == user.id)
        .execution_options(populate_existing=True)
    ).first()
    if not block:
        return False
    if block.is_gcal:
        raise ValueError("Imported Google events are read-only")
    if expected_revision is not None and block.revision != expected_revision:
        raise ValueError("This event changed; reload before deleting")
    block.revision += 1
    outbox.enqueue(session, block, "delete")
    session.delete(block)
    changed(session, owner)
    if commit:
        session.commit()
    return True


def delete_blocks_by_flags(
    session, user, *, is_default=None, is_gcal=None, is_pending=None, preset_source=None
):
    lock_calendar(session, user.id)
    ids = [
        b.id
        for b in user_blocks(session, user.id)
        if not b.is_gcal
        and all(
            expected is None or getattr(b, attr) == expected
            for attr, expected in (
                ("is_default", is_default),
                ("is_gcal", is_gcal),
                ("is_pending", is_pending),
                ("preset_source", preset_source),
            )
        )
    ]
    for block_id in ids:
        delete_block(session, user, block_id, commit=False)
    session.commit()
    return len(ids)


def compute_free_blocks(session, user, start_dt_str, total_hours, max_days=MAX_SEARCH_DAYS, end_dt_str=None):
    from app.domain.availability import allocate

    blocks = []
    for block in user_blocks(session, user.id):
        blocks.append({**block_to_dict(block), "starts_at": block.starts_at, "ends_at": block.ends_at})
    return allocate(blocks, start_dt_str, total_hours, user.timezone, max_days)


def detect_conflicts(session, user, date_str):
    slots = sorted(slots_for_date(session, user, date_str), key=lambda b: b["startMinutes"])
    return [
        {"a": a, "b": b}
        for index, a in enumerate(slots)
        for b in slots[index + 1 :]
        if b["startMinutes"] < a["endMinutes"]
    ]
