"""Regression coverage adapted from the original calendar feature tests."""

import pytest
from sqlmodel import select

from app.db.models import AgentMessage, AgentSession, User


def test_messages_are_ordered_and_user_scoped(client, db):
    owner = db.exec(select(User).where(User.email == "browser@example.com")).one()
    conversation = AgentSession(user_id=owner.id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    db.add(AgentMessage(user_id=owner.id, session_id=conversation.id, role="user", content="first"))
    db.add(AgentMessage(user_id=owner.id, session_id=conversation.id, role="assistant", content="second"))
    db.commit()
    assert [m["content"] for m in client.get(f"/api/agent/sessions/{conversation.id}/messages").json()] == [
        "first",
        "second",
    ]
    assert client.get("/api/agent/sessions/nonexistent/messages").status_code == 404


@pytest.mark.parametrize(
    "start,end", [("2030-01-01", "2030-02-20"), ("bad", "2030-01-01"), ("2030-01-02", "2030-01-01")]
)
def test_calendar_range_rejects_invalid_or_excessive_dates(client, start, end):
    assert client.get("/api/slots/range", params={"start": start, "end": end}).status_code == 400


def test_calendar_assets_are_served(client):
    for name in [
        "js/planner.js",
        "js/agent.js",
        "js/calendar-core.js",
        "js/calendar.js",
        "css/calendar.css",
        "css/planner.css",
    ]:
        assert client.get("/assets/" + name).status_code == 200


def test_background_api_returns_202_and_deduplicates(client):
    payload = {"prompt": "Plan a meeting", "request_id": "same-request"}
    first = client.post("/api/agent/chat", json=payload)
    second = client.post("/api/agent/chat", json=payload)
    assert first.status_code == 202
    assert second.json()["run_id"] == first.json()["run_id"]
    assert first.json()["status"] == "queued"
    assert client.get("/api/agent/runs/nonexistent").status_code == 404
    assert client.post("/api/agent/runs/nonexistent/cancel").status_code == 404


def test_active_conversation_cannot_start_another_run(client):
    first = client.post("/api/agent/chat", json={"prompt": "Plan"})
    session_id = first.json()["session_id"]
    assert (
        client.post("/api/agent/chat", json={"prompt": "Another", "session_id": session_id}).status_code
        == 409
    )
    run_id = first.json()["run_id"]
    assert client.post(f"/api/agent/runs/{run_id}/cancel").status_code == 200
    assert (
        client.post("/api/agent/chat", json={"prompt": "Replacement", "session_id": session_id}).status_code
        == 202
    )


def test_invalid_times_and_dates_rejected(client):
    for start, end, day in [
        ("25:00", "26:00", "2030-01-01"),
        ("10:00", "09:00", "2030-01-01"),
        ("10:00", "11:00", "2030-02-30"),
    ]:
        assert client.post("/api/slots", json={"date": day, "start": start, "end": end}).status_code == 400


def test_operational_metrics_are_user_scoped(client):
    client.post("/api/agent/chat", json={"prompt": "Metrics test", "request_id": "metrics-run"})
    result = client.get("/api/evals/metrics")
    assert result.status_code == 200
    assert result.json()["runs"] == {"queued": 1}
    assert result.json()["model_attempts"] == 0
