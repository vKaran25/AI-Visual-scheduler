"""Google integration regressions; every Google API boundary is mocked."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select


from app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from app.db.models import Block, User
from app.db.session import get_session
from app.main import app
from app.agents import tools
from app.services import auth_service, calendar_service


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="google-test@example.com", password_hash="unused")
        session.add(user)
        session.commit()
        session.refresh(user)
        yield session, user
    engine.dispose()


@pytest.fixture
def client(db):
    session, user = db
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        assert user.id is not None
        test_client.cookies.set(auth_service.AUTH_COOKIE, auth_service.create_access_token(user.id))
        yield test_client
    app.dependency_overrides.clear()


def _block(session, user, label, *, source=None, is_gcal=False, pending=False):
    block = Block(user_id=user.id, date="2030-01-01", start="10:00", end="11:00",
                  start_minutes=600, end_minutes=660, label=label,
                  is_gcal=is_gcal, preset_source=source, is_pending=pending, session_id="plan")
    session.add(block)
    session.commit()
    session.refresh(block)
    return block


def _labels(session):
    return {block.label for block in session.exec(select(Block)).all()}


def _event(label, start, end, private=None):
    return {"summary": label, "start": {"dateTime": start}, "end": {"dateTime": end},
            "extendedProperties": {"private": private or {}}}


class FakeEvents:
    def __init__(self, pages, fail=None):
        self.pages = pages
        self.fail = fail
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        events = self

        class Request:
            def execute(self):
                if events.fail == (kwargs["calendarId"], kwargs.get("pageToken")):
                    raise RuntimeError("Google unavailable")
                return events.pages[kwargs["calendarId"], kwargs.get("pageToken")]

        return Request()


class FakeService:
    def __init__(self, events):
        self._events = events

    def events(self):
        return self._events


def _mock_calendar(monkeypatch, events):
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda user: FakeService(events))
    monkeypatch.setattr(calendar_service, "get_managed_calendar_id", lambda service: "managed")
    monkeypatch.setattr(calendar_service, "GOOGLE_CALENDAR_TIMEZONE", "America/New_York")
    calendar_service.last_gcal_sync_time_by_user.clear()


def test_sync_pages_overnight_and_preserves_local_and_legacy(db, monkeypatch):
    session, user = db
    _block(session, user, "old imported", source=calendar_service.GOOGLE_IMPORT_SOURCE, is_gcal=True)
    legacy_import = _block(session, user, "untagged legacy import", is_gcal=True)
    legacy_import.session_id = None
    session.add(legacy_import)
    session.commit()
    _block(session, user, "local plan")
    _block(session, user, "legacy exported plan", is_gcal=True)
    pages = {
        ("primary", None): {"items": [_event("late", "2030-01-01T23:00:00-05:00", "2030-01-02T01:00:00-05:00")], "nextPageToken": "page2"},
        ("primary", "page2"): {"items": [_event("second page", "2030-01-03T13:00:00-05:00", "2030-01-03T14:00:00-05:00")]},
        ("managed", None): {"items": [_event("our export", "2030-01-01T10:00:00-05:00", "2030-01-01T11:00:00-05:00", {"scheduler_user_id": str(user.id)})]},
    }
    events = FakeEvents(pages)
    _mock_calendar(monkeypatch, events)
    assert calendar_service.sync_gcal_events(session, user, force=True) is True
    assert _labels(session) == {"local plan", "legacy exported plan", "late", "second page"}
    late = list(session.exec(select(Block).where(Block.label == "late")).all())
    assert [(b.date, b.start, b.end, b.preset_source) for b in late] == [
        ("2030-01-01", "23:00", "24:00", calendar_service.GOOGLE_IMPORT_SOURCE),
        ("2030-01-02", "00:00", "01:00", calendar_service.GOOGLE_IMPORT_SOURCE),
    ]
    assert [call["pageToken"] for call in events.calls] == [None, "page2", None]
    assert calendar_service.sync_gcal_events(session, user) is True
    assert len(events.calls) == 3  # cache updated only after success


def test_all_day_event_blocks_every_covered_day():
    from zoneinfo import ZoneInfo

    event = {"summary": "Away", "start": {"date": "2030-01-02"}, "end": {"date": "2030-01-04"}}
    blocks = calendar_service._event_blocks(event, "primary", ZoneInfo("UTC"))
    assert [(block["date"], block["start"], block["end"]) for block in blocks] == [
        ("2030-01-02", "00:00", "24:00"), ("2030-01-03", "00:00", "24:00"),
    ]
    event["transparency"] = "transparent"
    assert calendar_service._event_blocks(event, "primary", ZoneInfo("UTC")) == []


def test_sync_failure_on_second_page_never_erases_imports(db, monkeypatch):
    session, user = db
    _block(session, user, "keep import", source=calendar_service.GOOGLE_IMPORT_SOURCE, is_gcal=True)
    events = FakeEvents({("primary", None): {"items": [], "nextPageToken": "page2"}}, fail=("primary", "page2"))
    _mock_calendar(monkeypatch, events)
    assert calendar_service.sync_gcal_events(session, user, force=True) is False
    assert _labels(session) == {"keep import"}
    assert user.id not in calendar_service.last_gcal_sync_time_by_user


def test_disconnect_deletes_only_tagged_imports(db, monkeypatch):
    session, user = db
    _block(session, user, "import", source=calendar_service.GOOGLE_IMPORT_SOURCE, is_gcal=True)
    _block(session, user, "legacy local export", is_gcal=True)
    monkeypatch.setattr(calendar_service, "token_path", lambda user: "nonexistent-google-token")
    calendar_service.disconnect_google(session, user)
    assert _labels(session) == {"legacy local export"}


def test_export_failure_is_visible_and_keeps_confirmed_plan(db, monkeypatch):
    session, user = db
    _block(session, user, "confirm me", pending=True)
    monkeypatch.setattr(calendar_service, "get_gcal_credentials", lambda user: object())
    monkeypatch.setattr(calendar_service, "insert_calendar_event", lambda user, block: False)
    accepted, failed_ids = tools.commit_pending_plan(session, user, "plan")
    assert len(accepted) == 1
    assert failed_ids == [str(accepted[0]["id"])]
    confirmed = session.exec(select(Block).where(Block.label == "confirm me")).one()
    assert confirmed.is_pending is False and confirmed.is_gcal is False


def test_oauth_requires_same_browser_user_and_unexpired_state(client, db, monkeypatch):
    session, user = db
    saved = []
    monkeypatch.setattr(calendar_service, "build_authorization_url", lambda state: ("https://accounts.google.test/auth?state=" + state, state, None))
    monkeypatch.setattr(calendar_service, "save_callback_credentials", lambda *args, **kwargs: saved.append((args, kwargs)))
    monkeypatch.setattr(calendar_service, "sync_gcal_events", lambda *args, **kwargs: True)
    login = client.get("/api/google/oauth/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    initiating_token = client.cookies.get(auth_service.AUTH_COOKIE)
    callback = "/api/google/oauth/callback?state=" + state + "&code=mock-code&next=https://evil.example"
    client.cookies.set(auth_service.AUTH_COOKIE, state)
    assert client.get("/api/me").status_code == 401  # OAuth state is not an access token.
    # A different valid access token for the same user cannot complete this flow.
    other_token = jwt.encode({"sub": str(user.id), "type": "access",
                              "exp": datetime.now(timezone.utc) + timedelta(hours=2)}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    client.cookies.set(auth_service.AUTH_COOKIE, other_token)
    assert client.get(callback).status_code == 400
    client.cookies.set(auth_service.AUTH_COOKIE, other_token)
    other_user = User(email="another@example.com", password_hash="unused")
    session.add(other_user)
    session.commit()
    client.cookies.set(auth_service.AUTH_COOKIE, auth_service.create_access_token(other_user.id))
    assert client.get(callback).status_code == 400
    client.cookies.set(auth_service.AUTH_COOKIE, initiating_token)
    expired = jwt.encode({"sub": str(user.id), "type": "google_oauth", "cookie": "ignored",
                          "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    assert client.get("/api/google/oauth/callback", params={"state": expired, "code": "mock"}).status_code == 400
    ok = client.get(callback)
    assert ok.status_code == 200
    assert "evil.example" not in ok.text
    assert saved and saved[0][0][0].id == user.id
    assert saved[0][0][1].startswith(calendar_service.get_google_redirect_uri())
    assert client.get("/api/google/oauth/callback", params={"state": state, "error": "access_denied"}).status_code == 400
    assert len(saved) == 1


def test_pkce_verifier_is_reproducible_across_requests(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "fake-secret")
    state = "signed-state"
    url, returned_state, verifier = calendar_service.build_authorization_url(state=state)
    assert returned_state == state
    assert parse_qs(urlparse(url).query)["state"] == [state]
    assert parse_qs(urlparse(url).query).get("code_challenge_method") == ["S256"]
    assert len(verifier) == 43
    assert calendar_service.create_oauth_flow(state).code_verifier == verifier
    assert calendar_service._code_verifier("another-state") != verifier


def test_export_uses_configured_timezone_and_next_day_for_midnight(db, monkeypatch):
    session, user = db
    block = _block(session, user, "midnight plan")
    block.start, block.end, block.start_minutes, block.end_minutes = "23:00", "24:00", 1380, 1440
    inserted = []

    class Request:
        def execute(self):
            return {}

    class Events:
        def insert(self, **kwargs):
            inserted.append(kwargs)
            return Request()

    _mock_calendar(monkeypatch, FakeEvents({}))
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda user: FakeService(Events()))
    assert calendar_service.insert_calendar_event(user, block) is True
    body = inserted[0]["body"]
    assert body["start"]["dateTime"].startswith("2030-01-01T23:00:00-05:00")
    assert body["end"]["dateTime"].startswith("2030-01-02T00:00:00-05:00")
    assert body["extendedProperties"]["private"]["scheduler_block_id"] == str(block.id)


def test_cookie_policy_and_local_cors(monkeypatch):
    for secure, same_site in [(False, "lax"), (True, "none")]:
        monkeypatch.setattr(auth_service, "COOKIE_SECURE", secure)
        monkeypatch.setattr(auth_service, "COOKIE_SAMESITE", same_site)
        response = Response()
        auth_service.set_auth_cookie(response, "token")
        header = response.headers["set-cookie"]
        assert ("Secure" in header) == secure
        assert "samesite=" + same_site in header.lower()
        response = Response()
        auth_service.clear_auth_cookie(response)
        assert ("Secure" in response.headers["set-cookie"]) == secure
    with TestClient(app) as c:
        for origin in ("http://localhost:3000", "https://predestinationai.netlify.app"):
            response = c.options("/api/me", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
            assert response.headers["access-control-allow-origin"] == origin
            assert response.headers["access-control-allow-credentials"] == "true"
