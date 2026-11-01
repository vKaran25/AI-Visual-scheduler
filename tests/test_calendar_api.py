from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlmodel import Session, select

from app.db.models import Block, User
from app.services import scheduler_service as calendar


def payload(start="09:00", end="10:00", **extra):
    return {"date": "2030-01-01", "start": start, "end": end, "label": "Meeting", **extra}


def test_auth_and_user_isolation(client):
    other = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
        __import__("app.main", fromlist=["app"]).app
    )
    assert other.get("/api/slots").status_code == 401
    assert client.post("/api/slots", json=payload()).status_code == 201
    other.post("/api/auth/signup", json={"email": "other@example.com", "password": "password123"})
    assert other.get("/api/slots?date=2030-01-01").json() == []
    assert other.put("/api/slots/1", json={"label": "Hacked"}).status_code == 404


def test_native_date_json_and_free_time(db, user):
    item = calendar.create_block(db, user, payload())
    db.expire_all()
    assert db.get(Block, item.id).date == "2030-01-01"
    assert db.get(Block, item.id).starts_at.tzinfo
    result = calendar.compute_free_blocks(db, user, "2030-01-01T10:00", 1.1)
    assert result["fulfilled"] and result["totalAllocated"] >= 1.1
    assert result["allocated"][0]["end"] == "11:06"


@pytest.mark.parametrize("hours", ["inf", "nan", "0", "-1"])
def test_invalid_free_time_is_400(client, hours):
    assert client.get("/api/free", params={"hours": hours}).status_code == 400


def test_weekly_and_range(client):
    assert client.post("/api/slots", json=payload(repeatDays=[1])).status_code == 201
    data = client.get("/api/slots/range?start=2030-01-01&end=2030-01-07").json()
    assert len(data["2030-01-01"]) == 1
    assert data["2030-01-02"] == []
    assert client.get("/api/slots/range?start=2030-01-01&end=2030-05-01").status_code == 400


def test_imported_events_are_read_only(db, user, client):
    browser = db.exec(select(User).where(User.email == "browser@example.com")).one()
    block = calendar.create_block(db, browser, payload(is_gcal=True), skip_overlap=True)
    assert client.put(f"/api/slots/{block.id}", json={"label": "Change"}).status_code == 400
    assert client.delete(f"/api/slots/{block.id}").status_code == 409


def test_preset_rollback(db, user):
    calendar.create_block(db, user, payload("08:30", "10:00"))
    from app.services.preset_service import apply_preset

    with pytest.raises(ValueError):
        apply_preset(db, user, "student")
    db.rollback()
    assert len(calendar.user_blocks(db, user.id)) == 1


def test_concurrent_overlap_writes_are_serialized(postgres, db, user):
    user_id = user.id
    db.commit()

    def attempt():
        with Session(postgres, expire_on_commit=False) as session:
            owner = session.get(User, user_id)
            try:
                calendar.create_block(session, owner, payload())
                return "created"
            except ValueError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ["conflict", "created"]


def test_decision_requires_revision_and_origin_is_checked(client):
    assert client.post("/api/agent/confirm", json={"session_id": "x", "draft_id": "x"}).status_code == 422
    assert (
        client.post("/api/slots", json=payload(), headers={"origin": "https://untrusted.example"}).status_code
        == 403
    )
    assert client.get("/api/me").headers["cache-control"] == "no-store"


def test_memory_proposals_are_explicit_and_owned(client, db):
    from app.db.models import Memory, MemoryProposal

    owner = db.exec(select(User).where(User.email == "browser@example.com")).one()
    proposal = MemoryProposal(user_id=owner.id, content="Prefer short study sessions", source_key="test")
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    assert not db.exec(select(Memory)).all()
    assert (
        client.post(f"/api/memory-proposals/{proposal.id}/decision", json={"accept": True}).status_code == 200
    )
    assert len(db.exec(select(Memory)).all()) == 1
    client.post(f"/api/memory-proposals/{proposal.id}/decision", json={"accept": True})
    assert len(db.exec(select(Memory)).all()) == 1
