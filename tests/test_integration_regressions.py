"""Cross-feature API regressions using an isolated database and no network."""
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import AgentMessage, AgentSession, Block, Memory, User
from app.db.session import get_session
from app.main import app
from app.services import auth_service


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="integration@example.com", password_hash="unused")
        session.add(user)
        session.commit()
        session.refresh(user)
        yield session, user
    engine.dispose()


@pytest.fixture
def client(db):
    session, user = db
    assert user.id is not None
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        test_client.cookies.set(auth_service.AUTH_COOKIE, auth_service.create_access_token(user.id))
        yield test_client
    app.dependency_overrides.clear()


def test_session_messages_are_ordered_and_user_scoped(client, db):
    session, user = db
    new = client.post("/api/agent/new-session")
    assert new.status_code == 200
    sid = new.json()["session_id"]
    UUID(hex=sid)
    session.add_all([
        AgentMessage(user_id=user.id, session_id=sid, role="user", content="Schedule tomorrow"),
        AgentMessage(user_id=user.id, session_id=sid, role="assistant", content="What time?"),
    ])
    session.commit()
    result = client.get(f"/api/agent/sessions/{sid}/messages")
    assert result.status_code == 200
    assert [(m["role"], m["content"]) for m in result.json()] == [
        ("user", "Schedule tomorrow"), ("assistant", "What time?")
    ]
    other = User(email="other@example.com", password_hash="unused")
    session.add(other)
    session.commit()
    assert other.id is not None
    client.cookies.set(auth_service.AUTH_COOKIE, auth_service.create_access_token(other.id))
    assert client.get(f"/api/agent/sessions/{sid}/messages").status_code == 404
    assert client.get("/api/agent/sessions").json() == []


def test_google_export_warning_does_not_hide_local_confirmation(client, db, monkeypatch):
    from app.services import calendar_service

    session, user = db
    sid = client.post("/api/agent/new-session").json()["session_id"]
    session.add(Block(user_id=user.id, session_id=sid, is_pending=True,
                      date="2030-01-02", start="12:00", end="13:00",
                      start_minutes=720, end_minutes=780, label="Keep my plan"))
    session.commit()
    monkeypatch.setattr(calendar_service, "get_gcal_credentials", lambda user: object())
    monkeypatch.setattr(calendar_service, "sync_gcal_events", lambda *args, **kwargs: True)
    monkeypatch.setattr(calendar_service, "insert_calendar_event", lambda *args, **kwargs: False)
    result = client.post("/api/agent/confirm", json={"session_id": sid})
    assert result.status_code == 200
    assert result.json()["success"] is True and result.json()["count"] == 1
    assert "saved locally" in result.json()["warning"]
    assert session.get(AgentSession, sid).status == "confirmed"
    block = session.exec(select(Block).where(Block.session_id == sid)).one()
    assert not block.is_pending and not block.is_gcal
    repeat = client.post("/api/agent/confirm", json={"session_id": sid}).json()
    assert repeat["success"] is False and repeat["count"] == 0


def test_partial_preset_application_rolls_back(client, db):
    session, user = db
    existing = Block(user_id=user.id, date="2030-01-02", start="09:00", end="10:00",
                     start_minutes=540, end_minutes=600, label="My class")
    session.add(existing)
    session.commit()
    result = client.post("/api/presets/student/apply", json={"clear_existing": False})
    assert result.status_code == 400
    assert [b.label for b in session.exec(select(Block)).all()] == ["My class"]


def test_replace_preset_validates_before_deleting(client, db):
    session, user = db
    existing = Block(user_id=user.id, date="2030-01-02", start="09:00", end="10:00",
                     start_minutes=540, end_minutes=600, label="Keep me")
    session.add(existing)
    session.commit()
    created = client.post("/api/custom-presets", json={"name": "Undated", "blocks": [
        {"start": "12:00", "end": "13:00", "label": "Invisible", "repeatDays": []}
    ]})
    assert created.status_code == 200
    result = client.post(f"/api/presets/custom:{created.json()['id']}/apply", json={"clear_existing": True})
    assert result.status_code == 400
    assert [b.label for b in session.exec(select(Block)).all()] == ["Keep me"]


def test_invalid_block_time_and_date_are_rejected(client, db):
    for date, start, end in [
        ("2030-13-02", "12:00", "13:00"),
        ("2030-01-02", "25:00", "26:00"),
        ("2030-01-02", "12:75", "13:00"),
        ("2030-01-02", "12:00", "24:15"),
    ]:
        response = client.post("/api/slots", json={"date": date, "start": start, "end": end})
        assert response.status_code == 400, response.text
    assert client.get("/api/slots?date=2030-13-02").status_code == 400


def test_memory_alias_is_available_to_agent_and_facts_are_scoped(client, db):
    session, user = db
    result = client.post("/api/memory", json={"type": "preference", "content": "Early mornings"})
    assert result.status_code == 200
    assert result.json()["type"] == "pref"
    assert [m.content for m in session.exec(select(Memory).where(Memory.type == "pref")).all()] == ["Early mornings"]
    assert client.post("/api/memory", json={"type": "fact", "content": "Due Friday"}).status_code == 400
    new_sid = client.post("/api/agent/new-session").json()["session_id"]
    fact = client.post("/api/memory", json={"type": "fact", "content": "Due Friday", "chat_session_id": new_sid})
    assert fact.status_code == 200 and fact.json()["chat_session_id"] == new_sid
    assert client.post("/api/memory", json={"type": "pref", "content": "  "}).status_code == 400
    assert client.post("/api/memory", json={"type": "unknown", "content": "anything"}).status_code == 422
    other = User(email="other@example.com", password_hash="unused")
    session.add(other)
    session.commit()
    assert other.id is not None
    client.cookies.set(auth_service.AUTH_COOKIE, auth_service.create_access_token(other.id))
    assert client.post("/api/memory", json={"type": "fact", "content": "Steal", "chat_session_id": new_sid}).status_code == 400


def test_memory_migration_updates_legacy_rows(monkeypatch):
    from app.db import session as db_module
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(email="migration@example.com", password_hash="unused"))
        session.commit()
        session.add(Memory(user_id=1, type="preference", content="Legacy preference"))
        session.commit()
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.create_db_and_tables()
    db_module.create_db_and_tables()
    with Session(engine) as session:
        assert session.exec(select(Memory)).one().type == "pref"
    engine.dispose()
