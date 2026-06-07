import os
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / f"ai_visual_scheduler_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"
os.environ["NVIDIA_API_KEY"] = "test-nvidia-key"
os.environ["GOOGLE_TOKEN_DIR"] = str(TEST_DB.parent / f"google_tokens_{uuid.uuid4().hex}")

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import User
from app.db.session import create_db_and_tables, engine
from app.main import app
from app.services import scheduler_service
from app.services.time_utils import snap_to_30_min

create_db_and_tables()


def signup_client(email: str = None) -> TestClient:
    client = TestClient(app)
    payload = {
        "email": email or f"{uuid.uuid4().hex}@example.com",
        "password": "password123",
    }
    response = client.post("/api/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    return client


def test_auth_signup_login_and_me():
    client = signup_client()
    response = client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["email"].endswith("@example.com")


def test_user_isolation_for_blocks():
    user_a = signup_client()
    user_b = signup_client()

    create_response = user_a.post(
        "/api/slots",
        json={
            "date": "2026-06-04",
            "start": "18:00",
            "end": "19:00",
            "label": "User A block",
            "color": "#d81b60",
            "repeatDays": [],
        },
    )
    assert create_response.status_code == 201, create_response.text

    a_slots = user_a.get("/api/slots?date=2026-06-04").json()
    b_slots = user_b.get("/api/slots?date=2026-06-04").json()

    assert any(slot["label"] == "User A block" for slot in a_slots)
    assert not any(slot["label"] == "User A block" for slot in b_slots)


def test_overlap_and_free_time_minimum():
    client = signup_client()

    first = client.post(
        "/api/slots",
        json={
            "date": "2026-06-04",
            "start": "10:00",
            "end": "11:00",
            "label": "Busy",
            "color": "#d81b60",
            "repeatDays": [],
        },
    )
    assert first.status_code == 201, first.text

    overlap = client.post(
        "/api/slots",
        json={
            "date": "2026-06-04",
            "start": "10:30",
            "end": "11:30",
            "label": "Overlap",
            "color": "#d81b60",
            "repeatDays": [],
        },
    )
    assert overlap.status_code == 400

    free = client.get("/api/free?start_dt=2026-06-04T10:45&hours=0.5")
    assert free.status_code == 200
    allocated = free.json()["allocated"]
    assert allocated[0]["start"] == "11:00"


def test_builtin_preset_and_custom_preset():
    client = signup_client()

    presets = client.get("/api/presets")
    assert presets.status_code == 200
    assert any(preset["id"] == "student" for preset in presets.json())

    applied = client.post("/api/presets/student/apply", json={"clear_existing": True})
    assert applied.status_code == 200, applied.text
    assert len(applied.json()["created"]) > 0

    custom = client.post(
        "/api/custom-presets",
        json={"name": "My student week", "description": "Saved test preset"},
    )
    assert custom.status_code == 200, custom.text

    refreshed = client.get("/api/presets").json()
    assert any(preset["name"] == "My student week" and preset["custom"] for preset in refreshed)


def test_memory_crud():
    client = signup_client()
    created = client.post("/api/memory", json={"type": "preference", "content": "I prefer studying in the morning."})
    assert created.status_code == 200, created.text
    memory_id = created.json()["id"]

    listed = client.get("/api/memory")
    assert listed.status_code == 200
    assert any(item["id"] == memory_id for item in listed.json())

    deleted = client.delete(f"/api/memory/{memory_id}")
    assert deleted.status_code == 200


def test_agent_creates_pending_plan_and_confirm(monkeypatch):
    client = signup_client()

    from app.agents import roadmap_agent

    call_count = 0
    def fake_completion(messages, provider="nvidia_nim", response_format=None, temperature=0.2):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return '{"facts": [], "intent": "plan"}'
        return """
        {
          "goal": "Study GitHub and interview basics",
          "days": [
            {
              "day": 1,
              "focus": "Git basics",
              "tasks": [{"title": "Learn commits and branches", "duration_minutes": 60}]
            }
          ]
        }
        """

    monkeypatch.setattr(roadmap_agent.llm_client, "chat_completion", fake_completion)

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "I want a roadmap to study GitHub over 7 days and prepare for interview",
            "start_after": "2026-06-04T08:00",
            "slack": 0.0,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["scheduled"]
    assert data["scheduled"][0]["is_pending"] is True

    confirmed = client.post("/api/agent/confirm", json={"session_id": data["session_id"]})
    assert confirmed.status_code == 200
    assert confirmed.json()["count"] == 1


def test_snap_to_30_min():
    assert snap_to_30_min(datetime(2026, 6, 4, 14, 0)) == datetime(2026, 6, 4, 14, 0)
    assert snap_to_30_min(datetime(2026, 6, 4, 14, 30)) == datetime(2026, 6, 4, 14, 30)
    assert snap_to_30_min(datetime(2026, 6, 4, 14, 15)) == datetime(2026, 6, 4, 14, 30)
    assert snap_to_30_min(datetime(2026, 6, 4, 14, 45)) == datetime(2026, 6, 4, 15, 0)
    assert snap_to_30_min(datetime(2026, 6, 4, 23, 45)) == datetime(2026, 6, 5, 0, 0)
    assert snap_to_30_min(datetime(2026, 6, 4, 14, 0, 33)) == datetime(2026, 6, 4, 14, 0)


def test_free_time_default_start_snaps_to_30_minutes():
    client = signup_client()
    response = client.get("/api/free?hours=0.5")
    assert response.status_code == 200
    allocated = response.json()["allocated"]
    assert allocated, "Expected at least one allocated block"
    start_minutes = allocated[0]["startMinutes"]
    assert start_minutes % 30 == 0, f"Expected start snapped to 30-min mark, got {start_minutes}"


def test_agent_default_start_snaps_to_30_minutes(monkeypatch):
    client = signup_client()

    from app.agents import roadmap_agent

    call_count = 0
    def fake_completion(messages, provider="nvidia_nim", response_format=None, temperature=0.2):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return '{"facts": [], "intent": "plan"}'
        return """
        {
          "goal": "Quick task",
          "days": [{"day": 1, "focus": "Topic", "tasks": [{"title": "Task", "duration_minutes": 30}]}]
        }
        """

    monkeypatch.setattr(roadmap_agent.llm_client, "chat_completion", fake_completion)

    response = client.post(
        "/api/agent/chat",
        json={"prompt": "Plan a single short task", "slack": 0.0},
    )
    assert response.status_code == 200, response.text
    scheduled_date = response.json()["scheduled"][0]["date"]
    expected = snap_to_30_min(datetime.now()).date()
    assert scheduled_date == expected.isoformat(), (
        f"Expected agent to start on snapped date {expected}, got {scheduled_date}"
    )
