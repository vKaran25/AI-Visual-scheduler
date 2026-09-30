"""
Roadmap Agent — multi-step planning pipeline.

Memory model:
  - "pref" (permanent, global):  wake time, preferred session length, availability, etc.
  - "fact" (session-scoped):     what to study, deadline, num days for THIS planning task.

Facts from session A never bleed into session B.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4


from sqlalchemy import column
from sqlmodel import Session, select

from app.agents import tools as agent_tools
from app.db.models import AgentMessage, AgentSession, Block, User
from app.services import calendar_service, llm_client, memory_service, scheduler_service
from app.services.time_utils import minutes_to_time, snap_to_30_min, snap_to_5_min


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def _load_history(db: Session, session_id: str, user_id: int, max_messages: int = 20) -> str:
    rows = db.exec(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id, AgentMessage.user_id == user_id)
        .order_by(column("id").desc())
        .limit(max_messages)
    ).all()
    if not rows:
        return ""
    lines = []
    for msg in reversed(rows):
        role = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{role}: {msg.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_user_block(
    prompt: str,
    history: str,
    prefs: list[str],
    facts: list[str],
    cal_snapshot: str = "",
) -> str:
    parts = []
    if prefs:
        parts.append(
            "PERMANENT USER PREFERENCES (always apply to every plan):\n"
            + "\n".join(f"- {p}" for p in prefs)
        )
    if cal_snapshot:
        parts.append(f"CURRENT CALENDAR STATE (what is already booked):\n{cal_snapshot}")
    if facts:
        parts.append(
            "SESSION FACTS for this planning task (do NOT ask about these again):\n"
            + "\n".join(f"- {f}" for f in facts)
        )
    if history:
        parts.append(f"CONVERSATION HISTORY (do NOT re-ask questions already answered here):\n{history}")
    parts.append(f"User's latest message: {prompt}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class TriageAgent:
    """Single LLM call that extracts facts/prefs AND classifies intent."""

    def triage(
        self,
        prompt: str,
        prefs: list[str],
        facts: list[str],
        history: str = "",
        cal_snapshot: str = "",
    ) -> dict:
        system = """You are a scheduling assistant. Perform TWO tasks in a single response.

TASK 1 — EXTRACT INFORMATION: Pull out any NEW scheduling-relevant information.
  - "prefs": PERMANENT user preferences that apply to ALL future plans.
    Examples: wake-up time, preferred session length, days unavailable per week, break habits.
    Only extract if NOT already in permanent preferences.
  - "facts": FACTS specific to THIS planning task only (do NOT include permanent prefs here).
    Examples: study subject, deadline, total days needed, total hours for THIS topic.
    Only extract facts NOT already in session facts. Return empty list if nothing new.

TASK 2 — CLASSIFY INTENT: Classify into exactly ONE category:
  - "plan": User wants to schedule AND enough detail exists (subject, duration, timeframe).
  - "clarify": User mentions something schedulable but key details are still missing.
  - "chat": Message is PURELY off-topic with zero connection to planning. Use this rarely.

Return JSON only:
{"prefs": ["new pref 1"], "facts": ["new fact 1"], "intent": "plan|clarify|chat"}"""
        content = llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_block(prompt, history, prefs, facts, cal_snapshot)},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        try:
            parsed = json.loads(content)
            prefs_list = parsed.get("prefs", [])
            facts_list = parsed.get("facts", [])
            if not isinstance(prefs_list, list):
                prefs_list = []
            if not isinstance(facts_list, list):
                facts_list = []
            intent = str(parsed.get("intent", "chat")).strip().lower().strip('"').strip("'")
            if intent not in ("plan", "clarify", "chat"):
                if "clarif" in intent:
                    intent = "clarify"
                elif "plan" in intent or "schedul" in intent:
                    intent = "plan"
                else:
                    intent = "chat"
            return {
                "prefs": [str(p) for p in prefs_list if p],
                "facts": [str(f) for f in facts_list if f],
                "intent": intent,
            }
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise ValueError("Scheduling AI returned invalid triage JSON") from exc


class ChatAgent:
    def respond(
        self, prompt: str, prefs: list[str], facts: list[str], history: str = "", cal_snapshot: str = ""
    ) -> str:
        system = """You are a polite scheduling assistant. Keep responses brief and focused on scheduling.
IMPORTANT: Do NOT provide tutorials, lessons, academic explanations, or educational content.
If the user mentions a subject (e.g. math, programming), acknowledge it briefly and offer to help them schedule study time for it.
You help with scheduling tips and time management. Stay on topic.
Remember the earlier conversation context."""
        from app.agent.orchestrator import run_agent
        user_block = _build_user_block(prompt, history, prefs, facts, cal_snapshot)
        return run_agent(user_query=prompt, session_messages=user_block, system_prompt=system)


class ClarifyAgent:
    def ask(
        self, prompt: str, prefs: list[str], facts: list[str], history: str = "", cal_snapshot: str = ""
    ) -> str:
        system = """You are a polite, friendly scheduling assistant. The user wants to plan something but some details are missing.

CRITICAL RULES:
1. Read ALL permanent preferences, session facts, and conversation history CAREFULLY before responding.
2. NEVER re-ask for information the user has already provided — in this message, in the history, or in known facts/prefs.
3. Acknowledge what you already know (e.g. "Great, so you're studying X for Y days...").
4. Only ask for details that are GENUINELY still missing.
5. Ask at most 1-2 short, polite, specific questions.
6. Do NOT give tutorials or educational content.

To build a schedule you typically need: what to study/do, total hours or per-session duration, and timeframe or deadline.
If most details are already known, summarize them and ask only what's missing."""
        return llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_block(prompt, history, prefs, facts, cal_snapshot)},
            ],
            temperature=0.3,
        )


class PlannerAgent:
    def plan(
        self, prompt: str, prefs: list[str], facts: list[str], history: str = "", cal_snapshot: str = ""
    ) -> dict:
        system = """
You are a practical study roadmap planner.
You MUST strictly respect ALL constraints from the conversation:
- Session duration (e.g. "1hr sessions" means each task is 60 minutes)
- Number of days
- Total hours
- Any other user-specified constraints from permanent preferences or session facts

Review conversation history and ALL facts carefully before planning. Do NOT ignore constraints.

Return JSON only:
{
  "goal": "short goal",
  "title": "3-5 word session title (e.g. Redis 7-Day Plan)",
  "days": [
    {"day": 1, "focus": "topic", "tasks": [{"title": "task", "duration_minutes": 60}]}
  ]
}
Keep every task at least 30 minutes. Prefer 1-3 tasks per day.
"""
        content = llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_block(prompt, history, prefs, facts, cal_snapshot)},
            ],
            response_format={"type": "json_object"},
        )
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Scheduling AI returned invalid plan JSON") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Scheduling AI plan must be a JSON object")
        if "days" not in parsed or not isinstance(parsed["days"], list):
            raise ValueError("Planner did not return days")
        for day in parsed["days"]:
            if not isinstance(day, dict) or "tasks" not in day or not isinstance(day["tasks"], list):
                raise ValueError("Each day must have a tasks list")

        return parsed


class SchedulerAgent:
    def schedule(self, session: Session, user: User, plan: dict, session_id: str, start_after: str | None = None, slack: float = 0.0, *, new_session: AgentSession | None = None) -> list[dict]:
        if user.id is None:
            raise ValueError("User must be saved before scheduling")
        if not isinstance(slack, (int, float)) or not math.isfinite(slack) or slack < 0:
            raise ValueError("slack must be a finite non-negative number")
        try:
            requested_start = datetime.fromisoformat(start_after) if start_after else None
        except (TypeError, ValueError) as exc:
            raise ValueError("start_after must be an ISO date-time") from exc
        now = datetime.now(requested_start.tzinfo) if requested_start else datetime.now()
        search_start = snap_to_5_min(max(requested_start, now)) if requested_start else snap_to_30_min(now)

        days = plan.get("days")
        if not isinstance(days, list) or not days:
            raise ValueError("Planner returned no days to schedule")
        existing = scheduler_service.user_blocks(session, user.id)
        previous = [b for b in existing if b.is_pending and b.session_id == session_id]
        previous_ids = {b.id for b in previous}
        busy = [b for b in existing if b.id not in previous_ids]
        proposed = []
        seen_days = set()
        for day in days:
            if not isinstance(day, dict):
                raise ValueError("Each plan day must be an object")
            day_number = day.get("day")
            if isinstance(day_number, bool) or not isinstance(day_number, int) or day_number < 1 or day_number in seen_days:
                raise ValueError(f"Invalid or duplicate plan day: {day_number!r}")
            seen_days.add(day_number)
            try:
                date = (search_start.date() + timedelta(days=day_number - 1)).isoformat()
            except (OverflowError, ValueError) as exc:
                raise ValueError(f"Plan day {day_number} is out of range") from exc
            tasks = day.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                raise ValueError(f"Plan day {day_number} has no tasks")
            cursor = search_start.hour * 60 + search_start.minute if day_number == 1 else 8 * 60
            occupied = scheduler_service.merge_slots([
                (b.start_minutes, b.end_minutes) for b in busy
                if scheduler_service.slot_applies_to_date(b, date)
            ] + [
                (b["start_minutes"], b["end_minutes"]) for b in proposed if b["date"] == date
            ])
            for task in tasks:
                if not isinstance(task, dict):
                    raise ValueError(f"Plan day {day_number} contains an invalid task")
                duration = task.get("duration_minutes")
                if isinstance(duration, bool) or not isinstance(duration, int) or duration < 30:
                    raise ValueError(f"Plan day {day_number} task {task.get('title', '')!r} needs an integer duration of at least 30 minutes")
                expanded = duration * (1 + slack)
                if not math.isfinite(expanded):
                    raise ValueError("Task duration with slack is too large")
                minutes = math.ceil(expanded)
                label = task.get("title") or "Study task"
                candidate = cursor
                for begin, end in occupied:
                    if candidate + minutes <= begin:
                        break
                    if candidate < end and candidate + minutes > begin:
                        candidate = end
                if candidate + minutes > 1440:
                    raise ValueError(
                        f"Cannot fit day {day_number} task {label!r} ({minutes} minutes) "
                        f"contiguously on {date} after {minutes_to_time(cursor)}"
                    )
                proposed.append({
                    "date": date, "start_minutes": candidate, "end_minutes": candidate + minutes,
                    "start": minutes_to_time(candidate), "end": minutes_to_time(candidate + minutes),
                    "label": label, "color": "#7c6aff", "repeatDays": [],
                })
                occupied = scheduler_service.merge_slots(occupied + [(candidate, candidate + minutes)])
                cursor = candidate + minutes

        # No previous draft is touched unless every requested task can be placed.
        try:
            if new_session is not None:
                agent_session = new_session
            else:
                agent_session = session.get(AgentSession, session_id)
            if agent_session is not None:
                agent_session.draft_revision = uuid4().hex
                session.add(agent_session)
            for block in previous:
                session.delete(block)
            session.flush()
            scheduled = []
            for item in proposed:
                block = scheduler_service.create_block(
                    session, user, item, is_pending=True, session_id=session_id, commit=False
                )
                scheduled.append(scheduler_service.block_to_dict(block))
            session.commit()
            return scheduled
        except Exception:
            session.rollback()
            raise


class ConflictAgent:
    def detect(self, session: Session, user: User, scheduled: list[dict]) -> list[dict]:
        dates = sorted({block["date"] for block in scheduled if block.get("date")})
        conflicts = []
        for date in dates:
            conflicts.extend(agent_tools.detect_conflicts(session, user, date))
        return conflicts


class ReviewAgent:
    def review(self, plan: dict, scheduled: list[dict], conflicts: list[dict]) -> dict:
        goal = plan.get("goal", "Study plan")
        total_minutes = sum(
            (b.get("end_minutes", 0) or 0) - (b.get("start_minutes", 0) or 0)
            for b in scheduled if b.get("start_minutes") is not None
        )
        if not total_minutes:
            total_minutes = sum(
                (int(b["end"].split(":")[0]) * 60 + int(b["end"].split(":")[1])) -
                (int(b["start"].split(":")[0]) * 60 + int(b["start"].split(":")[1]))
                for b in scheduled
            )
        by_date: dict[str, list[dict]] = {}
        for b in scheduled:
            by_date.setdefault(b["date"], []).append(b)
        days_summary = []
        for date in sorted(by_date):
            day_blocks = sorted(by_date[date], key=lambda x: x["start"])
            total_day = sum(
                (int(b["end"].split(":")[0]) * 60 + int(b["end"].split(":")[1])) -
                (int(b["start"].split(":")[0]) * 60 + int(b["start"].split(":")[1]))
                for b in day_blocks
            )
            days_summary.append({
                "date": date,
                "blocks": [{"start": b["start"], "end": b["end"], "label": b.get("label", "Task")} for b in day_blocks],
                "day_minutes": total_day,
            })
        return {
            "goal": goal,
            "total_hours": round(total_minutes / 60, 1),
            "num_days": len(by_date),
            "days": days_summary,
            "conflicts": conflicts,
            "num_blocks": len(scheduled),
        }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_roadmap_agent(
    session: Session,
    user: User,
    prompt: str,
    start_after: str | None = None,
    slack: float = 0.0,
    existing_session_id: str | None = None,
) -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt is required")
    if user.id is None:
        raise ValueError("User must be saved before planning")
    if isinstance(slack, bool) or not isinstance(slack, (int, float)) or not math.isfinite(slack) or slack < 0:
        raise ValueError("slack must be a finite non-negative number")

    # Generate an ID without persisting an empty session before the provider replies.
    history = ""
    if existing_session_id:
        prev = session.get(AgentSession, existing_session_id)
        if not prev or prev.user_id != user.id:
            raise ValueError("Session not found")
        session_id = existing_session_id
        history = _load_history(session, session_id, user.id)
        cal_snapshot = prev.calendar_snapshot or ""
    else:
        session_id = uuid4().hex
        cal_snapshot = memory_service.get_calendar_snapshot(session, user)

    # ── Load memory — SCOPED correctly ───────────────────────────────────
    # Permanent prefs: global, always included
    prefs = [m.content for m in memory_service.list_prefs(session, user)]
    # Session facts: scoped to THIS session only
    facts = [m.content for m in memory_service.list_session_facts(session, user, session_id)]

    # ── Triage: extract new prefs/facts + classify intent ────────────────
    response = ""
    plan = None
    review = None
    try:
        triage = TriageAgent().triage(prompt, prefs, facts, history, cal_snapshot)
        new_prefs = triage["prefs"]
        new_facts = triage["facts"]
        intent = triage["intent"]
        prefs = new_prefs + prefs
        facts = new_facts + facts
        if intent == "chat":
            response = ChatAgent().respond(prompt, prefs, facts, history, cal_snapshot)
        elif intent == "clarify":
            response = ClarifyAgent().ask(prompt, prefs, facts, history, cal_snapshot)
        else:
            plan = PlannerAgent().plan(prompt, prefs, facts, history, cal_snapshot)
    except llm_client.LLMProviderError as exc:
        return {
            "response": str(exc), "scheduled": [],
            "session_id": existing_session_id, "plan": None,
            "conflicts": [], "intent": "error",
        }

    new_session = AgentSession(
        id=session_id, user_id=user.id, prompt=prompt,
        status="active", calendar_snapshot=cal_snapshot,
    ) if not existing_session_id else None

    if intent == "plan":
        if plan is None:
            raise ValueError("Planner returned no plan")
        if calendar_service.get_gcal_credentials(user) is not None and not calendar_service.sync_gcal_events(session, user, force=True):
            raise ValueError("Google Calendar availability could not be refreshed; try again before planning")
        try:
            scheduled = SchedulerAgent().schedule(
                session, user, plan, session_id, start_after, slack, new_session=new_session
            )
        except Exception:
            session.rollback()
            raise
        conflicts = ConflictAgent().detect(session, user, scheduled)
        review = ReviewAgent().review(plan, scheduled, conflicts)
        response = _format_review(review)
    else:
        scheduled = []
        conflicts = []
        if new_session is not None:
            session.add(new_session)

    _update_last_accessed(session, session_id)
    if new_prefs:
        memory_service.save_prefs(session, user, new_prefs)
    if new_facts:
        memory_service.save_session_facts(session, user, session_id, new_facts)

    session.add(AgentMessage(user_id=user.id, session_id=session_id, role="user", content=prompt))
    session.add(AgentMessage(user_id=user.id, session_id=session_id, role="assistant", content=response))
    if intent != "plan":
        _auto_name_session(session, session_id, prompt)
        session.commit()
        return {
            "response": response, "scheduled": [], "session_id": session_id,
            "plan": None, "conflicts": [], "intent": intent,
        }

    # Update session title once we have a plan
    assert plan is not None and review is not None
    agent_session = session.get(AgentSession, session_id)
    if agent_session and not agent_session.title:
        agent_session.title = plan.get("title", plan.get("goal", "Untitled Plan"))[:80]
        session.add(agent_session)

    if agent_session is None:
        raise ValueError("Planning session was not saved")
    agent_session.status = "active"
    agent_session.finished_at = None
    session.commit()

    return {
        "response": response,
        "scheduled": scheduled,
        "draft_id": agent_session.draft_revision,
        "session_id": session_id,
        "plan": plan,
        "conflicts": conflicts,
        "intent": "plan",
        "review": review,
    }


def _format_review(review: dict) -> str:
    lines = [f"Draft roadmap: {review['goal']}", ""]
    for day in review["days"]:
        d = datetime.fromisoformat(day["date"])
        day_name = d.strftime("%a %d %b")
        h, m = divmod(day["day_minutes"], 60)
        duration_str = f"{h}h{m:02d}m" if m else f"{h}h"
        lines.append(f"{day_name} ({duration_str})")
        for block in day["blocks"]:
            lines.append(f"  {block['start']}–{block['end']}  {block['label']}")
        lines.append("")
    if review["conflicts"]:
        lines.append(f"Warning: {len(review['conflicts'])} conflict(s) need review.")
        lines.append("")
    lines.append(f"Total: {review['total_hours']}h across {review['num_days']} days, {review['num_blocks']} blocks.")
    lines.append("These blocks are pending. Confirm to save them, or reject to remove them.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _update_last_accessed(session: Session, session_id: str) -> None:
    """Bump last_accessed_at so 'restart time' is always current."""
    agent_session = session.get(AgentSession, session_id)
    if agent_session:
        agent_session.last_accessed_at = datetime.now(timezone.utc)
        session.add(agent_session)
        session.commit()


def _auto_name_session(session: Session, session_id: str, prompt: str) -> None:
    """Set a short title from the user's prompt if the session has no title yet."""
    agent_session = session.get(AgentSession, session_id)
    if agent_session and not agent_session.title:
        words = prompt.strip().split()
        # Take first 6 words, capitalise first, max 60 chars
        short = " ".join(words[:6])
        if len(words) > 6:
            short += "…"
        agent_session.title = short[:60]
        session.add(agent_session)


# ---------------------------------------------------------------------------
# Confirm / Reject
# ---------------------------------------------------------------------------

def confirm_agent_plan(session: Session, user: User, session_id: str, draft_id: str | None = None) -> dict:
    agent_session = session.get(AgentSession, session_id)
    if not agent_session or agent_session.user_id != user.id:
        return {"success": False, "count": 0, "error": "Session not found"}
    try:
        # Check before invoking tools (which may export to Google); the service
        # checks again atomically while accepting the pending blocks.
        pending = list(session.exec(select(Block).where(
            Block.user_id == user.id,
            Block.session_id == session_id,
            Block.is_pending == True,
        )).all())
        if not pending:
            return {"success": False, "count": 0, "error": "No pending draft to confirm"}
        if draft_id is not None and draft_id != agent_session.draft_revision:
            return {"success": False, "count": 0, "error": "This plan was replaced; review the latest draft before confirming"}
        if calendar_service.get_gcal_credentials(user) is not None and not calendar_service.sync_gcal_events(session, user, force=True):
            return {"success": False, "count": 0, "error": "Google Calendar availability could not be refreshed; try again before confirming"}
        scheduler_service.check_pending_conflicts(session, user, pending)
        accepted, export_failures = agent_tools.commit_pending_plan(session, user, session_id)
    except ValueError as exc:
        return {"success": False, "count": 0, "error": str(exc)}
    agent_session.status = "confirmed"
    agent_session.finished_at = datetime.now(timezone.utc)
    session.add(agent_session)
    session.commit()
    result = {"success": True, "count": len(accepted)}
    if export_failures:
        result["warning"] = "Plans were saved locally, but Google export failed for block IDs: " + ", ".join(export_failures)
    return result


def reject_agent_plan(session: Session, user: User, session_id: str, draft_id: str | None = None) -> dict:
    agent_session = session.get(AgentSession, session_id)
    if not agent_session or agent_session.user_id != user.id:
        return {"success": False, "error": "Session not found"}
    pending = session.exec(select(Block).where(Block.user_id == user.id, Block.session_id == session_id, Block.is_pending == True)).all()
    if draft_id is not None and draft_id != agent_session.draft_revision:
        return {"success": False, "error": "This plan was replaced; review the latest draft before rejecting"}
    agent_tools.reject_pending_plan(session, user, session_id)
    agent_session.status = "rejected"
    agent_session.finished_at = datetime.now(timezone.utc)
    session.add(agent_session)
    session.commit()
    return {"success": True}
