"""The talking assistant: the model picks an action, code decides whether it is allowed and performs it."""

import pytest
from sqlmodel import select

from app.db.models import AgentRun, Block, Draft
from app.domain.contracts import Understanding, VoiceTurn, WorkerOutput
from app.integrations.openrouter import ModelUnavailable
from app.runtime.worker import run_once
from app.services import calendar_tools, voice_agent

DAY = "2030-01-07"  # a Monday


def voice_model(monkeypatch, **choice):
    """The voice model always returns `choice`; record what it was shown."""
    seen = []

    def respond(role, prompt, data, output_type):
        assert role == "voice" and output_type is VoiceTurn
        seen.append(data)
        return VoiceTurn(**choice)

    monkeypatch.setattr("app.integrations.openrouter.respond", respond)
    return seen


def planner_model(monkeypatch, event):
    def generate(role, prompt, data, output_type, cache_key):
        if role == "orchestrator":
            return Understanding(intent="action")
        if role == "action":
            return WorkerOutput(actions=[{"kind": "create", "event": event}])
        raise AssertionError(role)

    monkeypatch.setattr("app.integrations.openrouter.generate", generate)


def draft_waiting(db, user, graph, monkeypatch):
    """Speak a request and let the planner produce a draft for approval."""
    planner_model(monkeypatch, {"date": DAY, "start": "18:00", "end": "19:00", "label": "Study group"})
    voice_model(
        monkeypatch, action="delegate", request="Add a study group on 7 Jan 2030 at 6 pm", say="On it."
    )
    reply = voice_agent.turn(db, user, "add a study group on 7 January 2030 at 6 pm", None, "voice-req-1")
    assert reply["action"] == "delegate" and reply["run"]["status"] == "queued"
    assert run_once(graph)
    db.expire_all()
    run = db.get(AgentRun, reply["run"]["run_id"])
    assert run.status == "awaiting_approval", run.error
    return reply["session_id"], run


def test_schedule_is_read_from_the_database_not_the_model(db, user, monkeypatch):
    calendar_tools.create_event(db, user, "Calculus lecture", DAY, "09:00", "10:30")
    voice_model(
        monkeypatch, action="read_schedule", start_date=DAY, end_date=DAY, say="You have a party at 3."
    )
    reply = voice_agent.turn(db, user, "what's on Monday 7 January 2030?", None, "voice-read-1")
    assert reply["say"] == "On Monday 7 January you have Calculus lecture at 9 AM."
    assert "party" not in reply["say"]


def test_free_time_answer_comes_from_the_calendar(db, user, monkeypatch):
    voice_model(monkeypatch, action="find_free_time", hours=2, start_date=DAY)
    reply = voice_agent.turn(
        db, user, "when am I free for two hours on 7 January 2030?", None, "voice-free-1"
    )
    assert reply["say"].startswith("You're free Monday 7 January from 8 AM to 10 AM")


def test_spoken_yes_approves_a_new_event_draft(db, user, graph, monkeypatch):
    session_id, run = draft_waiting(db, user, graph, monkeypatch)
    seen = voice_model(monkeypatch, action="approve", say="Saved!")
    reply = voice_agent.turn(db, user, "yes, save it", session_id, "voice-yes-1")
    assert "Study group" in seen[0]["draft_waiting_for_approval"]
    assert reply["action"] == "approve" and reply["say"] == "Saving it now."
    assert run_once(graph)
    db.expire_all()
    assert [b.label for b in db.exec(select(Block)).all()] == ["Study group"]


@pytest.mark.parametrize("words", ["hmm, maybe", "no, don't save it yet"])
def test_unclear_or_negative_words_never_approve(db, user, graph, monkeypatch, words):
    session_id, run = draft_waiting(db, user, graph, monkeypatch)
    voice_model(monkeypatch, action="approve")
    reply = voice_agent.turn(db, user, words, session_id, "voice-unclear-1")
    assert reply["action"] == "none" and "say yes" in reply["say"]
    db.expire_all()
    assert db.exec(select(Draft).where(Draft.run_id == run.id)).one().status == "pending"


def test_drafts_that_remove_events_need_a_tap(db, user, graph, monkeypatch):
    session_id, run = draft_waiting(db, user, graph, monkeypatch)
    draft = db.exec(select(Draft).where(Draft.run_id == run.id)).one()
    draft.operations = draft.operations + [{"kind": "delete", "block_id": 1, "expected_revision": 1}]
    db.add(draft)
    db.commit()
    voice_model(monkeypatch, action="approve")
    reply = voice_agent.turn(db, user, "yes", session_id, "voice-delete-1")
    assert reply["action"] == "none" and "tap Approve" in reply["say"]


def test_spoken_no_discards_the_draft(db, user, graph, monkeypatch):
    session_id, run = draft_waiting(db, user, graph, monkeypatch)
    voice_model(monkeypatch, action="reject")
    reply = voice_agent.turn(db, user, "no thanks", session_id, "voice-no-1")
    assert reply["action"] == "reject"
    assert run_once(graph)
    db.expire_all()
    assert db.exec(select(Draft).where(Draft.run_id == run.id)).one().status == "rejected"
    assert db.exec(select(Block)).all() == []


def test_approve_with_nothing_waiting_does_nothing(db, user, monkeypatch):
    voice_model(monkeypatch, action="approve")
    reply = voice_agent.turn(db, user, "yes", None, "voice-nothing-1")
    assert reply["action"] == "none" and "nothing waiting" in reply["say"]


def test_voice_endpoint_answers_and_degrades_gracefully(client, monkeypatch):
    voice_model(monkeypatch, action="none", say="Hi! What should we plan?")
    ok = client.post("/api/voice/turn", json={"transcript": "hello", "request_id": "voice-api-0001"})
    assert ok.status_code == 200 and ok.json()["say"] == "Hi! What should we plan?"

    def down(*args, **kwargs):
        raise ModelUnavailable("down")

    monkeypatch.setattr("app.integrations.openrouter.respond", down)
    degraded = client.post("/api/voice/turn", json={"transcript": "hello", "request_id": "voice-api-0002"})
    assert degraded.status_code == 200 and "can still type" in degraded.json()["say"]
    assert (
        client.post("/api/voice/turn", json={"transcript": "", "request_id": "voice-api-0003"}).status_code
        == 422
    )
