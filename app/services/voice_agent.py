"""Conversational voice agent: talks with the student and hands real calendar work to the planner.

The model only chooses an action for each spoken turn. Code checks the current state, performs the action
through the existing services, and builds every factual sentence (dates, times, events) from the database,
so the agent cannot invent events, and nothing is saved without the student's approval.
"""

import re
from datetime import date, timedelta

from sqlmodel import select

from app.agents import prompts
from app.db.models import AgentMessage, AgentRun, AgentSession, Draft
from app.domain.contracts import VoiceTurn
from app.domain.time import local_now
from app.integrations import openrouter
from app.schemas.agent import AgentChatRequest
from app.services import calendar_tools, run_service

AFFIRM = re.compile(
    r"\b(?:yes|yeah|yep|yup|sure|ok|okay|save|approve|confirm|go ahead|do it|sounds good|perfect|correct)\b",
    re.I,
)
NEGATE = re.compile(r"\b(?:no|nope|don't|dont|do not|discard|reject|cancel|stop|wait|not)\b", re.I)
LIVE = ("queued", "running", "awaiting_input", "awaiting_approval")


def clock(value: str) -> str:
    """'18:00' -> '6 PM', '09:30' -> '9:30 AM', '24:00' -> 'midnight'."""
    hour, minute = map(int, value.split(":"))
    if hour % 24 == 0 and minute == 0:
        return "midnight"
    suffix = "AM" if hour % 24 < 12 else "PM"
    hour12 = (hour % 12) or 12
    return f"{hour12}{':%02d' % minute if minute else ''} {suffix}"


def day_name(value) -> str:
    day = value if isinstance(value, date) else date.fromisoformat(str(value))
    return f"{day:%A} {day.day} {day:%B}"


def describe_event(event: dict) -> str:
    when = day_name(event["date"]) if event.get("date") else "every week"
    return f"{event.get('label') or 'an event'}, {when}, {clock(event['start'])} to {clock(event['end'])}"


def draft_summary(draft: Draft) -> str:
    parts = []
    for change in draft.preview.get("changes", []):
        if change["kind"] == "create":
            parts.append("add " + describe_event(change["event"]))
        elif change["kind"] == "delete":
            parts.append("remove " + describe_event(change["before"]))
        elif change["kind"] == "update":
            parts.append(
                "change " + describe_event(change["before"]) + " to " + describe_event(change["event"])
            )
        else:
            parts.append("save a template")
    return "; ".join(parts) or "no calendar changes"


def schedule_sentence(listing: dict) -> str:
    lines = []
    for day, events in listing["days"].items():
        if not events:
            lines.append(f"{day_name(day)} is free.")
            continue
        items = [f"{e['title']} at {clock(e['start'])}" for e in events[:6]]
        more = f", and {len(events) - 6} more" if len(events) > 6 else ""
        lines.append(f"On {day_name(day)} you have " + ", ".join(items) + more + ".")
    return " ".join(lines[:3]) or "Your calendar is clear."


def free_sentence(result: dict) -> str:
    slots = result.get("allocated", [])[:3]
    if not slots:
        return "I couldn't find enough free time in the next few weeks."
    spans = [f"{day_name(s['date'])} from {clock(s['start'])} to {clock(s['end'])}" for s in slots]
    return "You're free " + "; ".join(spans) + "."


def _conversation(db, user, session_id, transcript):
    if session_id:
        return run_service.owned(db, AgentSession, session_id, user)
    conversation = AgentSession(user_id=user.id, prompt=transcript, title=transcript[:60])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _latest_run(db, conversation):
    return db.exec(
        select(AgentRun).where(AgentRun.session_id == conversation.id).order_by(AgentRun.created_at.desc())
    ).first()


def _pending_draft(db, run):
    if not run or run.status != "awaiting_approval":
        return None
    return db.exec(
        select(Draft)
        .where(Draft.run_id == run.id, Draft.status == "pending")
        .order_by(Draft.created_at.desc())
    ).first()


def _remember(db, user, conversation, role, content, key):
    if content and not db.exec(select(AgentMessage).where(AgentMessage.operation_key == key)).first():
        db.add(
            AgentMessage(
                user_id=user.id, session_id=conversation.id, role=role, content=content, operation_key=key
            )
        )


def turn(db, user, transcript: str, session_id: str | None, request_id: str) -> dict:
    conversation = _conversation(db, user, session_id, transcript)
    run = _latest_run(db, conversation)
    draft = _pending_draft(db, run)
    now = local_now(user.timezone)
    history = db.exec(
        select(AgentMessage)
        .where(AgentMessage.session_id == conversation.id, AgentMessage.user_id == user.id)
        .order_by(AgentMessage.id.desc())
        .limit(6)
    ).all()
    decision = openrouter.respond(
        "voice",
        prompts.VOICE,
        {
            "said": transcript,
            "now": now.isoformat(),
            "timezone": user.timezone,
            "draft_waiting_for_approval": draft_summary(draft) if draft else None,
            "planner_question": run.pending.get("question")
            if run and run.status == "awaiting_input"
            else None,
            "planner_is_working": bool(run and run.status in ("queued", "running")),
            "recent_conversation": [{"role": m.role, "text": m.content[:300]} for m in reversed(history)],
        },
        VoiceTurn,
    )
    action, say, result = decision.action, decision.say.strip(), None
    try:
        if action == "approve":
            if not draft:
                action, say = "none", "There's nothing waiting for approval right now."
            elif not AFFIRM.search(transcript) or NEGATE.search(transcript):
                action, say = "none", "Just to be sure: say yes to save it, or no to discard it."
            elif any(op["kind"] != "create" for op in draft.operations):
                action, say = (
                    "none",
                    "This changes or removes existing events, so please tap Approve on screen.",
                )
            else:
                result = run_service.decision(db, user, conversation.id, draft.id, draft.revision, True)
                say = "Saving it now."
        elif action == "reject":
            if draft:
                result = run_service.decision(db, user, conversation.id, draft.id, draft.revision, False)
                say = "Okay, I've discarded that. Nothing was changed."
            elif run and run.status in LIVE:
                result = run_service.cancel(db, user, run.id)
                say = "Okay, I've stopped."
            else:
                action = "none"
        elif action == "cancel":
            if run and run.status in LIVE:
                result = run_service.cancel(db, user, run.id)
                say = "Okay, I've stopped."
            else:
                action, say = "none", say or "There's nothing running right now."
        elif action == "delegate":
            request = decision.request.strip() or transcript
            if run and run.status in ("awaiting_input", "awaiting_approval"):
                result = run_service.resume(
                    db, user, run.id, run.pending.get("interrupt_id"), {"answer": request}, request_id
                )
                say = say or "Got it, updating that."
            elif run and run.status in ("queued", "running"):
                action, say = "none", "I'm still working on your last request. One moment."
            else:
                result = run_service.enqueue(
                    db,
                    user,
                    AgentChatRequest(prompt=request, session_id=conversation.id, request_id=request_id),
                )
                say = say or "On it."
        elif action == "read_schedule":
            start = decision.start_date or now.date()
            end = min(max(decision.end_date or start, start), start + timedelta(days=6))
            say = schedule_sentence(calendar_tools.list_events(db, user, start.isoformat(), end.isoformat()))
        elif action == "find_free_time":
            day = decision.start_date
            since = f"{day.isoformat()}T08:00" if day and day > now.date() else None
            say = free_sentence(calendar_tools.find_free_time(db, user, decision.hours or 1, since))
    except ValueError:
        action, say = (
            "none",
            "That changed while we were talking. I've refreshed it; please check the screen.",
        )
    say = say or "Sorry, could you say that again?"
    # Planner requests store the student's words themselves; everything else is recorded here.
    if action not in ("delegate",):
        _remember(db, user, conversation, "user", transcript, f"voice:{user.id}:{request_id}:user")
    _remember(db, user, conversation, "assistant", say, f"voice:{user.id}:{request_id}:assistant")
    db.commit()
    return {
        "session_id": conversation.id,
        "say": say,
        "action": action,
        "run": run_service.describe(db, result) if isinstance(result, AgentRun) else None,
    }
