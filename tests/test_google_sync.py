"""Google is mocked at its boundary; actual persistence and outbox transactions are used."""

import json
from datetime import timedelta
from zoneinfo import ZoneInfo

import httplib2
from googleapiclient.errors import HttpError
from sqlmodel import select

from app.db.models import GoogleConnection, GoogleEventMapping, SyncJob, utc_now
from app.integrations import google, google_sync
from app.services import scheduler_service as calendar


class Reply:
    def __init__(self, value=None, error=None):
        self.value, self.error, self.headers = value, error, {}

    def execute(self):
        if self.error:
            raise self.error
        return self.value


def connected(db, user):
    db.add(GoogleConnection(user_id=user.id, credentials_ciphertext="mocked"))
    db.commit()


def test_all_day_overnight_and_timezone():
    full = {"start": {"date": "2030-01-01"}, "end": {"date": "2030-01-03"}}
    blocks = google._event_blocks(full, "primary", ZoneInfo("UTC"))
    assert [(b["date"], b["start"], b["end"]) for b in blocks] == [
        ("2030-01-01", "00:00", "24:00"),
        ("2030-01-02", "00:00", "24:00"),
    ]
    event = {"start": {"dateTime": "2030-01-01T23:00:00Z"}, "end": {"dateTime": "2030-01-02T01:00:00Z"}}
    blocks = google._event_blocks(event, "primary", ZoneInfo("UTC"))
    assert [(b["start"], b["end"]) for b in blocks] == [("23:00", "24:00"), ("00:00", "01:00")]
    assert google._event_blocks({**event, "status": "cancelled"}, "primary", ZoneInfo("UTC")) == []


def test_failed_import_retains_last_snapshot(db, user, monkeypatch):
    connected(db, user)
    calendar.create_block(
        db,
        user,
        {"date": "2030-01-01", "start": "09:00", "end": "10:00", "label": "Old import", "is_gcal": True},
        skip_overlap=True,
        preset_source="google_import:old",
    )

    class Events:
        def list(self, **kwargs):
            return Reply(error=RuntimeError("network failure"))

    class Service:
        def events(self):
            return Events()

    monkeypatch.setattr(google, "get_calendar_service", lambda user: Service())
    monkeypatch.setattr(google, "get_managed_calendar_id", lambda service, user=None: "managed")
    assert not google.sync_gcal_events(db, user, force=True)
    assert len(calendar.user_blocks(db, user.id)) == 1
    assert db.get(GoogleConnection, user.id).sync_error


def test_remote_success_then_timeout_does_not_duplicate_event(db, user, monkeypatch):
    connected(db, user)
    block = calendar.create_block(
        db, user, {"date": "2030-01-01", "start": "09:00", "end": "10:00", "label": "Meeting"}
    )
    store = {}
    calls = {"first": True, "update_first": True, "updates": 0}

    class Events:
        def insert(self, calendarId, body):
            if body["id"] in store:
                return Reply(error=HttpError(httplib2.Response({"status": "409"}), b'{"error":"exists"}'))
            store[body["id"]] = {**body, "etag": "etag-1"}
            if calls["first"]:
                calls["first"] = False
                return Reply(error=TimeoutError("response lost after commit"))
            return Reply(store[body["id"]])

        def get(self, calendarId, eventId):
            return Reply(store[eventId])

        def update(self, calendarId, eventId, body):
            calls["updates"] += 1
            store[eventId] = {**body, "id": eventId, "etag": "etag-2"}
            if calls["update_first"]:
                calls["update_first"] = False
                return Reply(error=TimeoutError("update response lost after commit"))
            return Reply(store[eventId])

    class Service:
        def events(self):
            return Events()

    monkeypatch.setattr(google, "get_calendar_service", lambda user: Service())
    monkeypatch.setattr(google, "get_managed_calendar_id", lambda service, user=None: "managed")
    assert google_sync.sync_once()
    job = db.exec(select(SyncJob)).one()
    db.refresh(job)
    assert job.status == "queued"
    job.available_at = utc_now() - timedelta(seconds=1)
    db.add(job)
    db.commit()
    assert google_sync.sync_once()
    db.refresh(job)
    assert job.status == "completed", job.error
    assert len(store) == 1
    assert db.exec(select(GoogleEventMapping)).one().block_id == block.id
    calendar.update_block(db, user, block.id, {"label": "Updated meeting"})
    assert google_sync.sync_once()
    update_job = db.exec(select(SyncJob).order_by(SyncJob.created_at.desc())).first()
    db.refresh(update_job)
    assert update_job.status == "queued"
    update_job.available_at = utc_now() - timedelta(seconds=1)
    db.add(update_job)
    db.commit()
    assert google_sync.sync_once()
    db.refresh(update_job)
    assert update_job.status == "completed", update_job.error
    assert calls["updates"] == 1
    assert len(store) == 1


def test_disconnect_preserves_local_events(db, user):
    connected(db, user)
    local = calendar.create_block(
        db, user, {"date": "2030-01-01", "start": "09:00", "end": "10:00", "label": "Local"}
    )
    calendar.create_block(
        db,
        user,
        {"date": "2030-01-01", "start": "10:00", "end": "11:00", "label": "Imported", "is_gcal": True},
        skip_overlap=True,
    )
    google.disconnect_google(db, user)
    assert [b.id for b in calendar.user_blocks(db, user.id)] == [local.id]
    assert db.get(GoogleConnection, user.id) is None
    assert all(j.status == "cancelled" for j in db.exec(select(SyncJob)).all())


def test_oauth_callback_requires_matching_browser_state(client, monkeypatch):
    assert client.get("/api/google/oauth/callback?code=abc&state=invalid").status_code == 400
    captured = {}

    def auth(state=None):
        captured["state"] = state
        return "https://accounts.google.com/mock", state, None

    monkeypatch.setattr(google, "build_authorization_url", auth)
    assert client.get("/api/google/oauth/login", follow_redirects=False).status_code == 307
    state = captured["state"]
    client.post("/api/auth/logout")
    client.post("/api/auth/signup", json={"email": "another@example.com", "password": "password123"})
    assert client.get("/api/google/oauth/callback", params={"code": "abc", "state": state}).status_code == 400


def test_credentials_are_encrypted(db, user, monkeypatch):
    class Credentials:
        def to_json(self):
            return json.dumps({"token": "secret-token"})

    class Flow:
        credentials = Credentials()

        def fetch_token(self, **kwargs):
            pass

    monkeypatch.setattr(google, "create_oauth_flow", lambda state: Flow())
    google.save_callback_credentials(user, "https://example.com", state="signed-state")
    record = db.get(GoogleConnection, user.id)
    assert "secret-token" not in record.credentials_ciphertext
    assert (
        json.loads(google.cipher().decrypt(record.credentials_ciphertext.encode()))["token"] == "secret-token"
    )


def test_import_preserves_fold_and_subminute_instants(db, user):
    user.timezone = "America/New_York"
    db.add(user)
    db.commit()
    event = {
        "start": {"dateTime": "2026-11-01T01:45:00-04:00"},
        "end": {"dateTime": "2026-11-01T01:15:00-05:00"},
    }
    rows = google._event_blocks(event, "primary", ZoneInfo(user.timezone))
    assert len(rows) == 1
    block = calendar.create_block(db, user, rows[0], skip_overlap=True)
    assert (block.ends_at - block.starts_at).total_seconds() == 1800
    event = {"start": {"dateTime": "2030-01-01T09:00:30Z"}, "end": {"dateTime": "2030-01-01T09:00:45Z"}}
    rows = google._event_blocks(event, "primary", ZoneInfo("UTC"))
    assert rows[0]["start"] == "09:00" and rows[0]["end"] == "09:01"
