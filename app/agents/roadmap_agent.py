import json
import time
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.db.models import AgentMessage, AgentSession, Memory, User
from app.agents import tools as agent_tools
from app.services import llm_client, memory_service
from app.services.time_utils import parse_positive_float, snap_to_30_min


def _load_history(db: Session, session_id: str, user_id: int, max_messages: int = 20) -> str:
    rows = db.exec(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id, AgentMessage.user_id == user_id)
        .order_by(AgentMessage.id)
        .limit(max_messages)
    ).all()
    if not rows:
        return ""
    lines = []
    for msg in rows:
        role = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{role}: {msg.content}")
    return "\n".join(lines)


def _load_facts(db: Session, user_id: int, limit: int = 30) -> list[str]:
    rows = db.exec(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.type == "fact")
        .order_by(Memory.created_at.desc())
        .limit(limit)
    ).all()
    return [m.content for m in rows]


def _build_user_block(prompt: str, history: str, memories: list[str], facts: list[str]) -> str:
    parts = []
    if facts:
        parts.append("KNOWN FACTS about this user (already provided — do NOT ask about these again):\n" + "\n".join(f"- {f}" for f in facts))
    if history:
        parts.append(f"CONVERSATION HISTORY (do NOT re-ask questions already answered here):\n{history}")
    if memories:
        parts.append(f"User preferences: {memories}")
    parts.append(f"User's latest message: {prompt}")
    return "\n\n".join(parts)


class FactAgent:
    def extract(self, prompt: str, history: str) -> list[str]:
        system = """Extract scheduling-relevant facts from the user's message and conversation.
Return a JSON array of short factual strings (1-2 lines each).
Extract:
- Study subjects and topics (e.g. "Studying maths: eigenvalues and matrix inverse")
- Time constraints and preferences (e.g. "Has 5 days to prepare", "Prefers 2hr sessions")
- Goals and deadlines (e.g. "Exam on June 12 at 9:30 AM", "Wants 15-20 total hours")
- Any other concrete scheduling-relevant details
Return [] if there are no extractable facts."""
        content = llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Conversation:\n{history}\n\nLatest message: {prompt}" if history else f"Message: {prompt}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return [str(f) for f in parsed if f]
            if isinstance(parsed, dict) and "facts" in parsed:
                return [str(f) for f in parsed["facts"] if f]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def save_facts(self, db: Session, user: User, facts: list[str]) -> int:
        existing = {m.content.lower().strip() for m in
                     db.exec(select(Memory).where(Memory.user_id == user.id, Memory.type == "fact")).all()}
        saved = 0
        for fact in facts:
            normalized = fact.lower().strip()
            if normalized not in existing:
                db.add(Memory(user_id=user.id, type="fact", content=fact.strip()))
                existing.add(normalized)
                saved += 1
        if saved:
            db.commit()
        return saved


class ClassifierAgent:
    def classify(self, prompt: str, memories: list[str], history: str = "", facts: list[str] | None = None) -> str:
        system = """You are a message classifier for a SCHEDULING application.
Classify the user's LATEST message into exactly ONE category:
- "plan": The user wants to schedule or plan tasks/study time AND enough detail exists (subject, duration/hours, timeframe) — either in this message or accumulated across the conversation history and known facts.
- "clarify": The user mentions studying, learning, preparing, or any schedulable activity, but key details are still missing (e.g. duration, timeframe, or topic). Also use this when the user provides new info that adds to an ongoing planning conversation.
- "chat": The message is PURELY off-topic (greetings, thanks, or completely unrelated). Use this ONLY when the message has zero connection to planning or studying.

IMPORTANT: This is a scheduling app. When in doubt between "clarify" and "chat", choose "clarify".
Review ALL conversation history and known facts before deciding. If enough detail has accumulated across messages, classify as "plan".
Return ONLY the category word, nothing else."""
        content = llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_block(prompt, history, memories, facts or [])},
            ],
            temperature=0.0,
        )
        result = content.strip().lower().strip('"').strip("'")
        if result not in ("plan", "clarify", "chat"):
            if "clarif" in result:
                return "clarify"
            if "plan" in result or "schedul" in result:
                return "plan"
            return "chat"
        return result


class ChatAgent:
    def respond(self, prompt: str, memories: list[str], history: str = "", facts: list[str] | None = None) -> str:
        system = """You are a polite scheduling assistant. Keep responses brief and focused on scheduling.
IMPORTANT: Do NOT provide tutorials, lessons, academic explanations, or educational content.
If the user mentions a subject (e.g. math, programming), acknowledge it briefly and offer to help them schedule study time for it.
You help with scheduling tips and time management. Stay on topic.
Remember the earlier conversation context."""
        return llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_block(prompt, history, memories, facts or [])},
            ],
            temperature=0.4,
        )


class ClarifyAgent:
    def ask(self, prompt: str, memories: list[str], history: str = "", facts: list[str] | None = None) -> str:
        system = """You are a polite, friendly scheduling assistant. The user wants to plan something but some details are missing.

CRITICAL RULES:
1. Read ALL known facts and conversation history CAREFULLY before responding.
2. NEVER re-ask for information the user has already provided — in this message, in the conversation history, or in known facts.
3. Acknowledge what you already know (e.g. "Great, so you're studying X for Y days...").
4. Only ask for details that are GENUINELY still missing.
5. Ask at most 1-2 short, polite, specific questions.
6. Do NOT give tutorials or educational content.

To build a schedule you typically need: what to study/do, total hours or per-session duration, and timeframe or deadline.
If most details are already known, summarize them and ask only what's missing."""
        return llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_block(prompt, history, memories, facts or [])},
            ],
            temperature=0.3,
        )


class PlannerAgent:
    def plan(self, prompt: str, memories: list[str], history: str = "", facts: list[str] | None = None) -> dict:
        system = """
You are a practical study roadmap planner.
You MUST strictly respect ALL constraints from the conversation:
- Session duration (e.g. "1hr sessions" means each task is 60 minutes)
- Number of days
- Total hours
- Any other user-specified constraints

Review the conversation history carefully before planning. Do NOT ignore constraints mentioned earlier.

Return JSON only:
{
  "goal": "short goal",
  "days": [
    {"day": 1, "focus": "topic", "tasks": [{"title": "task", "duration_minutes": 60}]}
  ]
}
Keep every task at least 30 minutes. Prefer 1-3 tasks per day.
"""
        content = llm_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_block(prompt, history, memories, facts or [])},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(content)


class CurriculumAgent:
    def refine(self, plan: dict) -> dict:
        if "days" not in plan or not isinstance(plan["days"], list):
            raise ValueError("Planner did not return days")
        return plan


class SchedulerAgent:
    def schedule(self, session: Session, user: User, plan: dict, session_id: str, start_after: str | None = None, slack: float = 0.0) -> list[dict]:
        search_start = datetime.fromisoformat(start_after) if start_after else snap_to_30_min(datetime.now())
        scheduled = []
        for day in plan["days"]:
            date = (search_start.date() + timedelta(days=int(day.get("day", 1)) - 1)).isoformat()
            current_start = f"{date}T08:00"
            for task in day.get("tasks", []):
                minutes = max(30, int(task.get("duration_minutes", 60)))
                minutes = round(minutes / 5) * 5
                minutes = round(minutes * (1.0 + slack) / 5) * 5
                free = agent_tools.find_free_time(session, user, current_start, minutes / 60.0)
                blocks = free.get("allocated", [])
                if not blocks:
                    continue
                block = blocks[0]
                db_block = agent_tools.create_pending_block(
                    session,
                    user,
                    session_id,
                    {
                        "date": block["date"],
                        "start": block["start"],
                        "end": block["end"],
                        "label": task.get("title", "Study task"),
                        "color": "#7c6aff",
                        "repeatDays": [],
                    },
                )
                scheduled.append(db_block)
                current_start = f"{block['date']}T{block['end']}"
        return scheduled


class ConflictAgent:
    def detect(self, session: Session, user: User, scheduled: list[dict]) -> list[dict]:
        dates = sorted({block["date"] for block in scheduled if block.get("date")})
        conflicts = []
        for date in dates:
            conflicts.extend(agent_tools.detect_conflicts(session, user, date))
        return conflicts


class ReviewAgent:
    def review(self, plan: dict, scheduled: list[dict], conflicts: list[str]) -> dict:
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


def run_roadmap_agent(session: Session, user: User, prompt: str, start_after: str | None = None, slack: float = 0.0, existing_session_id: str | None = None) -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt is required")
    slack = parse_positive_float(slack, 0.0) or 0.0

    history = ""
    if existing_session_id:
        prev = session.get(AgentSession, existing_session_id)
        if prev and prev.user_id == user.id:
            session_id = existing_session_id
            history = _load_history(session, session_id, user.id)
        else:
            session_id = str(int(time.time() * 1000))
    else:
        session_id = str(int(time.time() * 1000))

    # Ensure AgentSession exists so follow-up messages can load history
    if not session.get(AgentSession, session_id):
        session.add(AgentSession(
            id=session_id,
            user_id=user.id,
            prompt=prompt,
            status="active",
        ))
        session.commit()

    memories = [memory.content for memory in memory_service.retrieve_memories(session, user, prompt)]
    facts = _load_facts(session, user.id)

    fact_agent = FactAgent()
    new_facts = fact_agent.extract(prompt, history)
    if new_facts:
        fact_agent.save_facts(session, user, new_facts)
        facts = new_facts + facts

    session.add(AgentMessage(user_id=user.id, session_id=session_id, role="user", content=prompt))
    session.commit()

    intent = ClassifierAgent().classify(prompt, memories, history, facts)

    if intent == "chat":
        response = ChatAgent().respond(prompt, memories, history, facts)
        session.add(AgentMessage(user_id=user.id, session_id=session_id, role="assistant", content=response))
        session.commit()
        return {
            "response": response,
            "scheduled": [],
            "session_id": session_id,
            "plan": None,
            "conflicts": [],
            "intent": "chat",
        }

    if intent == "clarify":
        response = ClarifyAgent().ask(prompt, memories, history, facts)
        session.add(AgentMessage(user_id=user.id, session_id=session_id, role="assistant", content=response))
        session.commit()
        return {
            "response": response,
            "scheduled": [],
            "session_id": session_id,
            "plan": None,
            "conflicts": [],
            "intent": "clarify",
        }

    plan = CurriculumAgent().refine(PlannerAgent().plan(prompt, memories, history, facts))
    scheduled = SchedulerAgent().schedule(session, user, plan, session_id, start_after, slack)
    conflicts = ConflictAgent().detect(session, user, scheduled)
    review = ReviewAgent().review(plan, scheduled, conflicts)

    review_text = _format_review(review)
    session.add(AgentMessage(user_id=user.id, session_id=session_id, role="assistant", content=review_text))
    session.commit()

    return {
        "response": review_text,
        "scheduled": scheduled,
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


def confirm_agent_plan(session: Session, user: User, session_id: str) -> dict:
    accepted = agent_tools.commit_pending_plan(session, user, session_id)
    agent_session = session.get(AgentSession, session_id)
    if agent_session and agent_session.user_id == user.id:
        agent_session.status = "confirmed"
        session.add(agent_session)
        session.commit()
    return {"success": True, "count": len(accepted)}


def reject_agent_plan(session: Session, user: User, session_id: str) -> dict:
    agent_tools.reject_pending_plan(session, user, session_id)
    agent_session = session.get(AgentSession, session_id)
    if agent_session and agent_session.user_id == user.id:
        agent_session.status = "rejected"
        session.add(agent_session)
        session.commit()
    return {"success": True}
