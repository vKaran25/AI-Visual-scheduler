import os
import tempfile
import uuid
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / f"ai_visual_scheduler_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"
os.environ["NVIDIA_API_KEY"] = "test-nvidia-key"
os.environ["GOOGLE_TOKEN_DIR"] = str(TEST_DB.parent / f"google_tokens_{uuid.uuid4().hex}")

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import create_db_and_tables

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
    client.put("/api/settings/default-blocks", json={"enabled": False})

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
    client.put("/api/settings/default-blocks", json={"enabled": False})

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
    client.put("/api/settings/default-blocks", json={"enabled": False})

    from app.agents import roadmap_agent

    def fake_completion(messages, provider="nvidia_nim", response_format=None, temperature=0.2):
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
