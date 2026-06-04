import json
import time
from datetime import datetime, timedelta

from sqlmodel import Session

from app.db.models import AgentMessage, AgentSession, User
from app.agents import tools as agent_tools
from app.services import llm_client, memory_service
from app.services.time_utils import parse_positive_float


class PlannerAgent:
    def plan(self, prompt: str, memories: list[str]) -> dict:
        system = """
        You are a practical study roadmap planner.
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
                {"role": "user", "content": f"Relevant user memory: {memories}\n\nRequest: {prompt}"},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(content)


class CurriculumAgent:
    def refine(self, plan: dict) -> dict:
        # First version keeps this transparent: validate shape and leave refinement to the planner prompt.
        if "days" not in plan or not isinstance(plan["days"], list):
            raise ValueError("Planner did not return days")
        return plan


class SchedulerAgent:
    def schedule(self, session: Session, user: User, plan: dict, session_id: str, start_after: str | None = None, slack: float = 0.0) -> list[dict]:
        search_start = datetime.fromisoformat(start_after) if start_after else datetime.now()
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
    def review(self, plan: dict, scheduled: list[dict], conflicts: list[dict]) -> str:
        lines = [f"Draft roadmap: {plan.get('goal', 'Study plan')}", ""]
        for block in scheduled:
            lines.append(f"- {block['date']} {block['start']}-{block['end']}: {block['label']}")
        if conflicts:
            lines.append("")
            lines.append(f"Warning: {len(conflicts)} conflict(s) need review.")
        lines.append("")
        lines.append("These blocks are pending. Confirm to save them, or reject to remove them.")
        return "\n".join(lines)


def run_roadmap_agent(session: Session, user: User, prompt: str, start_after: str | None = None, slack: float = 0.0) -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt is required")
    slack = parse_positive_float(slack, 0.0) or 0.0
    session_id = str(int(time.time() * 1000))
    memories = [memory.content for memory in memory_service.retrieve_memories(session, user, prompt)]

    agent_session = AgentSession(id=session_id, user_id=user.id, prompt=prompt, provider="nvidia_nim")
    session.add(agent_session)
    session.add(AgentMessage(user_id=user.id, session_id=session_id, role="user", content=prompt))
    session.commit()

    plan = CurriculumAgent().refine(PlannerAgent().plan(prompt, memories))
    scheduled = SchedulerAgent().schedule(session, user, plan, session_id, start_after, slack)
    conflicts = ConflictAgent().detect(session, user, scheduled)
    review = ReviewAgent().review(plan, scheduled, conflicts)

    agent_session.summary = review
    session.add(agent_session)
    session.add(AgentMessage(user_id=user.id, session_id=session_id, role="assistant", content=review))
    session.commit()

    return {
        "response": review,
        "scheduled": scheduled,
        "session_id": session_id,
        "plan": plan,
        "conflicts": conflicts,
    }


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
