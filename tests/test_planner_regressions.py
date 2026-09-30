"""Offline regression tests for planning and pending-draft reliability."""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.agents import roadmap_agent
from app.db.models import AgentMessage, AgentSession, Block, User
from app.schemas.agent import AgentChatRequest
from app.services import llm_client, scheduler_service
from app.services.time_utils import snap_to_30_min


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="planner@example.com", password_hash="unused")
        session.add(user)
        session.commit()
        session.refresh(user)
        yield session, user
    engine.dispose()


def start_at(hour=9, minute=0, second=0):
    return (datetime.now() + timedelta(days=10)).replace(
        hour=hour, minute=minute, second=second, microsecond=0
    ).isoformat()


def plan(*days):
    return {"goal": "Study", "days": [
        {"day": index + 1, "tasks": [{"title": name, "duration_minutes": minutes} for name, minutes in tasks]}
        for index, tasks in enumerate(days)
    ]}


def blocks(db):
    session, user = db
    return list(session.exec(select(Block).where(Block.user_id == user.id)).all())


def add_block(db, date, start, end, **kwargs):
    session, user = db
    return scheduler_service.create_block(session, user, {
        "date": date, "start": start, "end": end, "label": "Busy", "repeatDays": []
    }, **kwargs)


def test_start_timestamp_and_exact_contiguous_duration(db):
    session, user = db
    start = start_at(9, 0, 1)
    day = start[:10]
    add_block(db, day, "09:05", "09:15")
    scheduled = roadmap_agent.SchedulerAgent().schedule(
        session, user, plan([("first", 37), ("second", 60)]), "draft", start
    )
    assert [(b["start"], b["end"]) for b in scheduled] == [("09:15", "09:52"), ("09:52", "10:52")]
    assert all(b["date"] == day and b["is_pending"] for b in scheduled)


def test_no_drift_to_next_day_and_no_partial_writes(db):
    session, user = db
    start = start_at(22, 0)
    day = start[:10]
    with pytest.raises(ValueError, match="day 1 task 'too long'.*contiguously"):
        roadmap_agent.SchedulerAgent().schedule(session, user, plan([("fits", 30), ("too long", 120)]), "draft", start)
    assert blocks(db) == []
    assert session.get(AgentSession, "draft") is None
    assert day == start[:10]


def test_replan_replaces_only_own_pending_and_rolls_back_failed_insert(db, monkeypatch):
    session, user = db
    start = start_at(9)
    planner = roadmap_agent.SchedulerAgent()
    original = planner.schedule(session, user, plan([("old", 45)]), "draft", start)
    other = planner.schedule(session, user, plan([("other", 30)]), "another", start)
    with pytest.raises(ValueError, match="Cannot fit"):
        planner.schedule(session, user, plan([("bad", 1500)]), "draft", start)
    assert {b.id for b in blocks(db)} == {original[0]["id"], other[0]["id"]}

    real_create = scheduler_service.create_block
    def broken_create(*args, **kwargs):
        if args[2]["label"] == "second":
            raise RuntimeError("insert failed")
        return real_create(*args, **kwargs)
    monkeypatch.setattr(scheduler_service, "create_block", broken_create)
    with pytest.raises(RuntimeError, match="insert failed"):
        planner.schedule(session, user, plan([("first", 30), ("second", 30)]), "draft", start)
    assert {b.id for b in blocks(db)} == {original[0]["id"], other[0]["id"]}
    monkeypatch.setattr(scheduler_service, "create_block", real_create)
    replaced = planner.schedule(session, user, plan([("replacement", 30)]), "draft", start)
    assert {b.id for b in blocks(db)} == {replaced[0]["id"], other[0]["id"]}


def test_confirm_rechecks_conflicts_and_does_not_confirm(db, monkeypatch):
    session, user = db
    start = start_at(9)
    session.add(AgentSession(id="draft", user_id=user.id, prompt="study"))
    session.commit()
    draft = roadmap_agent.SchedulerAgent().schedule(session, user, plan([("task", 60)]), "draft", start)
    add_block(db, start[:10], draft[0]["start"], draft[0]["end"], skip_overlap=True)
    monkeypatch.setattr(roadmap_agent.agent_tools, "commit_pending_plan", lambda *a: pytest.fail("should not export"))
    result = roadmap_agent.confirm_agent_plan(session, user, "draft")
    assert result["success"] is False and "Busy" in result["error"]
    assert session.get(Block, draft[0]["id"]).is_pending
    assert session.get(AgentSession, "draft").status != "confirmed"
    with pytest.raises(ValueError, match="Cannot confirm"):
        scheduler_service.accept_pending_slots(session, user, "draft")


def test_old_plan_actions_cannot_decide_new_draft(db, monkeypatch):
    session, user = db
    monkeypatch.setattr(roadmap_agent.TriageAgent, "triage", lambda *a: {"prefs": [], "facts": [], "intent": "plan"})
    monkeypatch.setattr(roadmap_agent.PlannerAgent, "plan", lambda *a: plan([("task", 60)]))
    first = roadmap_agent.run_roadmap_agent(session, user, "schedule", start_after=start_at())
    second = roadmap_agent.run_roadmap_agent(session, user, "replan", start_after=start_at(), existing_session_id=first["session_id"])
    assert first["draft_id"] != second["draft_id"]
    old_accept = roadmap_agent.confirm_agent_plan(session, user, second["session_id"], first["draft_id"])
    old_reject = roadmap_agent.reject_agent_plan(session, user, second["session_id"], first["draft_id"])
    assert not old_accept["success"] and "replaced" in old_accept["error"]
    assert not old_reject["success"] and "replaced" in old_reject["error"]
    assert len(blocks(db)) == 1 and blocks(db)[0].is_pending
    assert roadmap_agent.confirm_agent_plan(session, user, second["session_id"], second["draft_id"])["count"] == 1


def test_connected_google_refresh_failure_prevents_plan_and_confirmation(db, monkeypatch):
    from app.services import calendar_service

    session, user = db
    monkeypatch.setattr(roadmap_agent.TriageAgent, "triage", lambda *a: {"prefs": [], "facts": [], "intent": "plan"})
    monkeypatch.setattr(roadmap_agent.PlannerAgent, "plan", lambda *a: plan([("task", 60)]))
    monkeypatch.setattr(calendar_service, "get_gcal_credentials", lambda user: object())
    monkeypatch.setattr(calendar_service, "sync_gcal_events", lambda *a, **kw: False)
    with pytest.raises(ValueError, match="availability could not be refreshed"):
        roadmap_agent.run_roadmap_agent(session, user, "schedule", start_after=start_at())
    assert session.exec(select(AgentSession)).all() == []
    assert blocks(db) == []
    session.add(AgentSession(id="draft", user_id=user.id, prompt="study"))
    session.commit()
    add_block(db, start_at()[:10], "10:00", "11:00", is_pending=True, session_id="draft")
    confirmation = roadmap_agent.confirm_agent_plan(session, user, "draft")
    assert confirmation["success"] is False and "availability" in confirmation["error"]
    assert blocks(db)[0].is_pending


def test_midnight_endpoint_and_repeat_busy(db):
    session, user = db
    start = start_at(23, 30)
    scheduled = roadmap_agent.SchedulerAgent().schedule(session, user, plan([("midnight", 30)]), "draft", start)
    assert scheduled[0]["end"] == "24:00"
    assert scheduled[0]["date"] == start[:10]
    with pytest.raises(ValueError, match="Cannot fit day 1"):
        roadmap_agent.SchedulerAgent().schedule(session, user, plan([("one", 30), ("two", 30)]), "draft", start)
    assert len(blocks(db)) == 1


def test_create_block_flush_without_commit(db):
    session, user = db
    date = start_at()[:10]
    block = scheduler_service.create_block(session, user, {
        "date": date, "start": "12:00", "end": "13:00", "label": "draft"
    }, commit=False)
    assert block.id is not None
    session.rollback()
    assert blocks(db) == []


def test_recent_history_and_unique_session_ids(db, monkeypatch):
    session, user = db
    session.add(AgentSession(id="history", user_id=user.id, prompt="history"))
    session.add_all([AgentMessage(user_id=user.id, session_id="history", role="user", content=str(i)) for i in range(30)])
    session.commit()
    history = roadmap_agent._load_history(session, "history", user.id)
    assert "User: 9" not in history and "User: 10" in history and history.endswith("User: 29")

    monkeypatch.setattr(roadmap_agent.TriageAgent, "triage", lambda *a: {"prefs": [], "facts": [], "intent": "clarify"})
    monkeypatch.setattr(roadmap_agent.ClarifyAgent, "ask", lambda *a: "When?")
    first = roadmap_agent.run_roadmap_agent(session, user, "study?")
    second = roadmap_agent.run_roadmap_agent(session, user, "study?")
    assert first["session_id"] != second["session_id"]
    assert session.get(AgentSession, first["session_id"]) is not None
    assert roadmap_agent.confirm_agent_plan(session, user, first["session_id"]) == {
        "success": False, "count": 0, "error": "No pending draft to confirm"
    }


def test_provider_failure_returns_error_without_new_empty_session(db, monkeypatch):
    session, user = db
    def offline(*args, **kwargs):
        raise llm_client.LLMProviderError("Both providers unavailable")
    monkeypatch.setattr(llm_client, "chat_completion", offline)
    result = roadmap_agent.run_roadmap_agent(session, user, "plan this")
    assert result["intent"] == "error" and result["session_id"] is None
    assert "unavailable" in result["response"]
    assert session.exec(select(AgentSession)).all() == []


def test_failed_plan_does_not_create_an_empty_session(db, monkeypatch):
    session, user = db
    monkeypatch.setattr(roadmap_agent.TriageAgent, "triage", lambda *a: {"prefs": [], "facts": [], "intent": "plan"})
    monkeypatch.setattr(roadmap_agent.PlannerAgent, "plan", lambda *a: plan([("too late", 120)]))
    with pytest.raises(ValueError, match="Cannot fit day 1"):
        roadmap_agent.run_roadmap_agent(session, user, "schedule", start_after=start_at(23))
    assert session.exec(select(AgentSession)).all() == []
    assert blocks(db) == []


def test_llm_reports_both_provider_failures_without_network(monkeypatch):
    def fail_nim(*args):
        raise RuntimeError("NIM offline")
    def fail_groq(*args):
        raise RuntimeError("Groq offline")
    monkeypatch.setattr(llm_client, "_call_nvidia_nim", fail_nim)
    monkeypatch.setattr(llm_client, "_call_groq", fail_groq)
    with pytest.raises(llm_client.LLMProviderError, match="NIM offline.*Groq offline"):
        llm_client.chat_completion([{"role": "user", "content": "hello"}])


def test_slack_and_upward_second_snapping(db):
    for value in (-1, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            AgentChatRequest(prompt="plan", slack=value)
        with pytest.raises(ValueError, match="slack"):
            roadmap_agent.SchedulerAgent().schedule(db[0], db[1], plan([("task", 30)]), "draft", slack=value)
    assert snap_to_30_min(datetime(2030, 1, 1, 14, 0, 1)) == datetime(2030, 1, 1, 14, 30)
    session, user = db
    free = scheduler_service.compute_free_blocks(session, user, start_at(14, 0, 1), 0.5)
    assert free["allocated"][0]["start"] == "14:05"
    scheduled = roadmap_agent.SchedulerAgent().schedule(session, user, plan([("task", 37)]), "draft", start_at(), slack=0.1)
    assert scheduled[0]["endMinutes"] - scheduled[0]["startMinutes"] == 41
