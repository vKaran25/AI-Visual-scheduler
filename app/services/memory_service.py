"""
Memory service — session-aware memory management.

Two memory types:
  "pref"  → permanent user preferences (wake time, preferred session length, etc.)
             chat_session_id = None (global)
  "fact"  → session-scoped scheduling facts (topic, deadline, days for THIS plan)
             chat_session_id = <session_id>

Calendar snapshots are generated fresh on each new session start.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from app.db.models import AgentSession, Block, Memory, User


# ---------------------------------------------------------------------------
# Permanent preferences (global per user)
# ---------------------------------------------------------------------------

def list_prefs(session: Session, user: User) -> list[Memory]:
    """Returns all permanent user preferences (type='pref'). Always global."""
    return list(
        session.exec(
            select(Memory)
            .where(Memory.user_id == user.id, Memory.type == "pref")
            .order_by(Memory.created_at.desc())
        ).all()
    )


def save_prefs(session: Session, user: User, prefs: list[str]) -> int:
    """Persist new permanent preferences, deduplicating against existing ones."""
    existing = {
        m.content.lower().strip()
        for m in session.exec(
            select(Memory).where(Memory.user_id == user.id, Memory.type == "pref")
        ).all()
    }
    saved = 0
    for pref in prefs:
        normalized = pref.lower().strip()
        if normalized and normalized not in existing:
            session.add(Memory(user_id=user.id, type="pref", content=pref.strip(), chat_session_id=None))
            existing.add(normalized)
            saved += 1
    if saved:
        session.commit()
    return saved


# ---------------------------------------------------------------------------
# Session-scoped facts
# ---------------------------------------------------------------------------

def list_session_facts(session: Session, user: User, chat_session_id: str) -> list[Memory]:
    """Returns scheduling facts scoped to a specific planning session."""
    return list(
        session.exec(
            select(Memory)
            .where(
                Memory.user_id == user.id,
                Memory.type == "fact",
                Memory.chat_session_id == chat_session_id,
            )
            .order_by(Memory.created_at.desc())
        ).all()
    )


def save_session_facts(session: Session, user: User, chat_session_id: str, facts: list[str]) -> int:
    """Persist new session-scoped facts, deduplicating within the same session."""
    existing = {
        m.content.lower().strip()
        for m in session.exec(
            select(Memory).where(
                Memory.user_id == user.id,
                Memory.type == "fact",
                Memory.chat_session_id == chat_session_id,
            )
        ).all()
    }
    saved = 0
    for fact in facts:
        normalized = fact.lower().strip()
        if normalized and normalized not in existing:
            session.add(
                Memory(
                    user_id=user.id,
                    type="fact",
                    content=fact.strip(),
                    chat_session_id=chat_session_id,
                )
            )
            existing.add(normalized)
            saved += 1
    if saved:
        session.commit()
    return saved


# ---------------------------------------------------------------------------
# Calendar snapshot
# ---------------------------------------------------------------------------

def get_calendar_snapshot(session: Session, user: User, days_ahead: int = 14) -> str:
    """
    Returns a brief human-readable summary of confirmed (non-pending) calendar
    blocks for the next `days_ahead` days. Injected into new sessions so the
    agent is immediately aware of what's already scheduled.
    """
    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    today_str = today.isoformat()
    end_str = end_date.isoformat()

    blocks = list(
        session.exec(
            select(Block).where(
                Block.user_id == user.id,
                Block.is_pending == False,  # noqa: E712
            )
        ).all()
    )

    # Group confirmed blocks by date within the window
    by_date: dict[str, list[Block]] = {}
    for block in blocks:
        import json as _json
        repeat_days = _json.loads(block.repeat_days_json or "[]")
        if repeat_days:
            # Repeating block — find which dates in window it applies to
            current = today
            while current <= end_date:
                weekday = current.weekday()  # 0=Mon … 6=Sun
                if weekday in repeat_days:
                    ds = current.isoformat()
                    by_date.setdefault(ds, []).append(block)
                current += timedelta(days=1)
        elif block.date and today_str <= block.date <= end_str:
            by_date.setdefault(block.date, []).append(block)

    if not by_date:
        return f"Your calendar is empty for the next {days_ahead} days."

    lines = [f"Existing confirmed schedule for next {days_ahead} days:"]
    for date_str in sorted(by_date.keys()):
        day_blocks = sorted(by_date[date_str], key=lambda b: b.start_minutes)
        day_label = datetime.fromisoformat(date_str).strftime("%a %d %b")
        block_strs = ", ".join(f"{b.start}–{b.end} {b.label}" for b in day_blocks)
        lines.append(f"  {day_label}: {block_strs}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy API — kept for backward compatibility with existing /api/memory routes
# ---------------------------------------------------------------------------

def list_memories(session: Session, user: User) -> list[Memory]:
    """Returns ALL memories for the user (both prefs and facts). Used by /api/memory UI."""
    return list(
        session.exec(
            select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at.desc())
        ).all()
    )


def create_memory(session: Session, user: User, memory_type: str, content: str, chat_session_id: str | None = None) -> Memory:
    memory_type = "pref" if memory_type == "preference" else memory_type
    if memory_type not in ("pref", "fact"):
        raise ValueError("Memory type must be pref or fact")
    content = content.strip()
    if not content:
        raise ValueError("Memory content is required")
    if memory_type == "fact":
        owned_session = session.get(AgentSession, chat_session_id) if chat_session_id else None
        if not owned_session or owned_session.user_id != user.id:
            raise ValueError("Facts require a session owned by the user")
    elif chat_session_id:
        raise ValueError("Permanent preferences cannot be tied to a session")
    memory = Memory(user_id=user.id, type=memory_type, content=content, chat_session_id=chat_session_id)
    session.add(memory)
    session.commit()
    session.refresh(memory)
    return memory


def delete_memory(session: Session, user: User, memory_id: int) -> bool:
    memory = session.get(Memory, memory_id)
    if not memory or memory.user_id != user.id:
        return False
    session.delete(memory)
    session.commit()
    return True


def retrieve_memories(session: Session, user: User, query: str, limit: int = 8) -> list[Memory]:
    """Legacy fuzzy retrieval — returns prefs only (global), used by older code paths."""
    terms = [term.lower() for term in query.split() if len(term) > 2]
    memories = list_prefs(session, user)
    ranked = []
    for memory in memories:
        score = sum(1 for term in terms if term in memory.content.lower() or term in memory.type.lower())
        if score:
            memory.last_used_at = datetime.now(timezone.utc)
            session.add(memory)
        ranked.append((score, memory.created_at, memory))
    session.commit()
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [memory for _, _, memory in ranked[:limit]]
