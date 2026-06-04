import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.db.models import Block, User
from app.services.time_utils import (
    MAX_SEARCH_DAYS,
    MIN_FREE_BLOCK_MINUTES,
    minutes_to_time,
    normalize_repeat_days,
    parse_float,
    parse_positive_float,
    validate_time_range,
    weekday_for_date,
)

DEFAULT_BLOCKS = [
    {
        "date": None,
        "start": "00:00",
        "end": "06:00",
        "label": "Sleep",
        "color": "#4527a0",
        "repeatDays": [0, 1, 2, 3, 4, 5, 6],
        "is_default": True,
        "preset_source": "default",
    },
    {
        "date": None,
        "start": "08:30",
        "end": "17:00",
        "label": "Classes",
        "color": "#2e7d32",
        "repeatDays": [0, 1, 2, 3, 4],
        "is_default": True,
        "preset_source": "default",
    },
]


def block_to_dict(block: Block, display_date: str | None = None) -> dict:
    repeat_days = json.loads(block.repeat_days_json or "[]")
    return {
        "id": block.id,
        "date": display_date if display_date is not None else block.date,
        "start": block.start,
        "end": block.end,
        "startMinutes": block.start_minutes,
        "endMinutes": block.end_minutes,
        "label": block.label,
        "color": block.color,
        "repeatDays": repeat_days,
        "is_gcal": block.is_gcal,
        "is_default": block.is_default,
        "is_pending": block.is_pending,
        "session_id": block.session_id,
        "preset_source": block.preset_source,
    }


def merge_slots(slots):
    if not slots:
        return []
    s = sorted(slots, key=lambda x: x[0])
    merged = [list(s[0])]
    for start, end in s[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(x) for x in merged]


def user_blocks(session: Session, user_id: int) -> list[Block]:
    return list(session.exec(select(Block).where(Block.user_id == user_id)).all())


def slot_applies_to_date(block: Block, date_str: str) -> bool:
    repeat_days = json.loads(block.repeat_days_json or "[]")
    if repeat_days:
        return weekday_for_date(date_str) in repeat_days
    return block.date == date_str


def slots_for_date(session: Session, user: User, date_str: str) -> list[dict]:
    out = []
    for block in user_blocks(session, user.id):
        if block.is_default and not user.default_blocks_enabled:
            continue
        if slot_applies_to_date(block, date_str):
            out.append(block_to_dict(block, display_date=date_str))
    return out


def slot_overlaps(
    session: Session,
    user_id: int,
    start_minutes: int,
    end_minutes: int,
    date_str: str | None,
    repeat_days=None,
    ignore_id=None,
) -> Block | None:
    repeat_days = normalize_repeat_days(repeat_days or [])
    for block in user_blocks(session, user_id):
        if block.id == ignore_id:
            continue
        existing_days = json.loads(block.repeat_days_json or "[]")
        same_time = start_minutes < block.end_minutes and end_minutes > block.start_minutes
        if not same_time:
            continue
        if repeat_days:
            if existing_days and set(existing_days).intersection(repeat_days):
                return block
            if block.date and weekday_for_date(block.date) in repeat_days:
                return block
        elif date_str and slot_applies_to_date(block, date_str):
            return block
    return None


def validate_no_overlap(session: Session, user_id: int, start_minutes: int, end_minutes: int, date_str: str | None, repeat_days=None, ignore_id=None) -> None:
    if not date_str and not repeat_days:
        raise ValueError("Date or repeat days are required")
    conflict = slot_overlaps(session, user_id, start_minutes, end_minutes, date_str, repeat_days, ignore_id)
    if conflict:
        raise ValueError(f"Time overlaps with existing block: {conflict.label}")


def create_block(session: Session, user: User, data: dict, *, is_default=False, is_pending=False, session_id=None, preset_source=None, skip_overlap=False) -> Block:
    start_minutes, end_minutes = validate_time_range(data.get("start"), data.get("end"))
    repeat_days = normalize_repeat_days(data.get("repeatDays", []))
    date = None if repeat_days else data.get("date")
    if not skip_overlap:
        validate_no_overlap(session, user.id, start_minutes, end_minutes, date, repeat_days)
    block = Block(
        user_id=user.id,
        date=date,
        start=data.get("start"),
        end=data.get("end"),
        start_minutes=start_minutes,
        end_minutes=end_minutes,
        label=data.get("label", "Busy"),
        color=data.get("color", "#d81b60"),
        repeat_days_json=json.dumps(repeat_days),
        is_gcal=bool(data.get("is_gcal", False)),
        is_default=is_default,
        is_pending=is_pending,
        session_id=session_id,
        preset_source=preset_source,
    )
    session.add(block)
    session.commit()
    session.refresh(block)
    return block


def update_block(session: Session, user: User, block_id: int, data: dict) -> Block | None:
    block = session.get(Block, block_id)
    if not block or block.user_id != user.id:
        return None
    start = data.get("start", block.start)
    end = data.get("end", block.end)
    start_minutes, end_minutes = validate_time_range(start, end)
    repeat_days = normalize_repeat_days(data.get("repeatDays", json.loads(block.repeat_days_json or "[]")))
    date = data.get("date", block.date)
    if repeat_days:
        date = None
    validate_no_overlap(session, user.id, start_minutes, end_minutes, date, repeat_days, ignore_id=block_id)
    block.date = date
    block.start = start
    block.end = end
    block.start_minutes = start_minutes
    block.end_minutes = end_minutes
    block.label = data.get("label", block.label)
    block.color = data.get("color", block.color)
    block.repeat_days_json = json.dumps(repeat_days)
    session.add(block)
    session.commit()
    session.refresh(block)
    return block


def delete_block(session: Session, user: User, block_id: int) -> bool:
    block = session.get(Block, block_id)
    if not block or block.user_id != user.id:
        return False
    session.delete(block)
    session.commit()
    return True


def delete_blocks_by_flags(session: Session, user: User, *, is_default=None, is_gcal=None, is_pending=None, preset_source=None) -> int:
    blocks = user_blocks(session, user.id)
    count = 0
    for block in blocks:
        if is_default is not None and block.is_default != is_default:
            continue
        if is_gcal is not None and block.is_gcal != is_gcal:
            continue
        if is_pending is not None and block.is_pending != is_pending:
            continue
        if preset_source is not None and block.preset_source != preset_source:
            continue
        session.delete(block)
        count += 1
    session.commit()
    return count


def set_default_blocks_enabled(session: Session, user: User, enabled: bool) -> dict:
    user.default_blocks_enabled = bool(enabled)
    session.add(user)
    if enabled:
        existing_defaults = [b for b in user_blocks(session, user.id) if b.is_default and b.preset_source == "default"]
        if not existing_defaults:
            for block in DEFAULT_BLOCKS:
                create_block(session, user, block, is_default=True, preset_source="default", skip_overlap=True)
    else:
        delete_blocks_by_flags(session, user, is_default=True, preset_source="default")
    session.commit()
    return {"enabled": user.default_blocks_enabled}


def ensure_default_blocks(session: Session, user: User) -> None:
    if user.default_blocks_enabled:
        defaults = [b for b in user_blocks(session, user.id) if b.is_default and b.preset_source == "default"]
        if not defaults:
            for block in DEFAULT_BLOCKS:
                create_block(session, user, block, is_default=True, preset_source="default", skip_overlap=True)


def compute_free_blocks(session: Session, user: User, start_dt_str: str, total_hours: float, max_days: int = MAX_SEARCH_DAYS) -> dict:
    start_dt = datetime.fromisoformat(start_dt_str)
    total_minutes = max(0, round(total_hours * 60))
    total_minutes = round(total_minutes / 5) * 5
    total_minutes = max(total_minutes, MIN_FREE_BLOCK_MINUTES)
    allocated = []
    remaining = total_minutes
    current_dt = start_dt

    for _ in range(max_days):
        if remaining <= 0:
            break
        date_str = current_dt.strftime("%Y-%m-%d")
        start_min = current_dt.hour * 60 + current_dt.minute if current_dt.date() == start_dt.date() else 0
        rem = start_min % 5
        if rem != 0:
            start_min += (5 - rem)
        merged_busy = merge_slots([(s["startMinutes"], s["endMinutes"]) for s in slots_for_date(session, user, date_str)])
        free_gaps = []
        cursor = start_min
        for bstart, bend in merged_busy:
            if bend <= cursor:
                continue
            if bstart > cursor:
                gs, ge = cursor, bstart
                rm = gs % 5
                if rm != 0:
                    gs += (5 - rm)
                ge -= (ge % 5)
                if ge - gs >= MIN_FREE_BLOCK_MINUTES:
                    free_gaps.append((gs, ge))
            cursor = max(cursor, bend)
        if cursor < 1440:
            gs, ge = cursor, 1440
            rm = gs % 5
            if rm != 0:
                gs += (5 - rm)
            ge -= (ge % 5)
            if ge - gs >= MIN_FREE_BLOCK_MINUTES:
                free_gaps.append((gs, ge))
        for gstart, gend in free_gaps:
            if remaining <= 0:
                break
            use = min(gend - gstart, remaining)
            if use < MIN_FREE_BLOCK_MINUTES:
                continue
            dh, dm = divmod(use, 60)
            duration_str = f"{dh}h {dm}m" if dh and dm else f"{dh}h" if dh else f"{dm}m"
            allocated.append({
                "date": date_str,
                "start": minutes_to_time(gstart),
                "end": minutes_to_time(gstart + use),
                "startMinutes": gstart,
                "endMinutes": gstart + use,
                "duration": use / 60,
                "durationStr": duration_str,
            })
            remaining -= use
        next_day = (current_dt + timedelta(days=1)).date()
        current_dt = datetime(next_day.year, next_day.month, next_day.day)

    return {
        "allocated": allocated,
        "totalAllocated": (total_minutes - remaining) / 60,
        "requested": total_hours,
        "fulfilled": remaining <= 0,
        "missing": remaining / 60,
    }


def accept_pending_slots(session: Session, user: User, session_id: str, mark_as_gcal=False) -> list[Block]:
    blocks = list(session.exec(select(Block).where(Block.user_id == user.id, Block.session_id == session_id, Block.is_pending == True)).all())
    for block in blocks:
        block.is_pending = False
        if mark_as_gcal:
            block.is_gcal = True
        session.add(block)
    session.commit()
    return blocks


def reject_pending_slots(session: Session, user: User, session_id: str) -> None:
    blocks = list(session.exec(select(Block).where(Block.user_id == user.id, Block.session_id == session_id, Block.is_pending == True)).all())
    for block in blocks:
        session.delete(block)
    session.commit()


def detect_conflicts(session: Session, user: User, date_str: str) -> list[dict]:
    slots = sorted(slots_for_date(session, user, date_str), key=lambda x: x["startMinutes"])
    conflicts = []
    for idx, slot in enumerate(slots):
        for other in slots[idx + 1:]:
            if other["startMinutes"] >= slot["endMinutes"]:
                break
            conflicts.append({"a": slot, "b": other})
    return conflicts

