"""Google OAuth, availability import and idempotent outbox delivery."""

import base64
import hashlib
import hmac
import json
import os
from datetime import date, datetime, timedelta, timezone
from datetime import time as day_time
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlmodel import Session, select

from app.core.config import (
    APP_BASE_URL,
    GOOGLE_TOKEN_ENCRYPTION_KEY,
    JWT_SECRET_KEY,
)
from app.db.models import Block, GoogleConnection, GoogleEventMapping, SyncJob
from app.db.session import engine
from app.db.transactions import changed, lock_calendar

GOOGLE_IMPORT_SOURCE = "google_import"


def cipher():
    if not GOOGLE_TOKEN_ENCRYPTION_KEY:
        raise ValueError("Configure GOOGLE_TOKEN_ENCRYPTION_KEY before connecting Google")
    return Fernet(GOOGLE_TOKEN_ENCRYPTION_KEY.encode())


def get_google_redirect_uri():
    return os.getenv("GOOGLE_OAUTH_REDIRECT_URI") or f"{APP_BASE_URL}/api/google/oauth/callback"


def get_client_config():
    return {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [get_google_redirect_uri()],
        }
    }


def _code_verifier(state):
    return (
        base64.urlsafe_b64encode(hmac.new(JWT_SECRET_KEY.encode(), state.encode(), hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )


def create_oauth_flow(state=None):
    flow = Flow.from_client_config(
        get_client_config(),
        scopes=["https://www.googleapis.com/auth/calendar"],
        state=state,
        code_verifier=_code_verifier(state) if state else None,
    )
    flow.redirect_uri = get_google_redirect_uri()
    return flow


def build_authorization_url(state=None):
    flow = create_oauth_flow(state)
    url, state = flow.authorization_url(prompt="consent", access_type="offline", state=state)
    return url, state, getattr(flow, "code_verifier", None)


def save_callback_credentials(user, authorization_response, state=None, code_verifier=None):
    flow = create_oauth_flow(state)
    flow.fetch_token(
        authorization_response=authorization_response, code_verifier=code_verifier or _code_verifier(state)
    )
    encrypted = cipher().encrypt(flow.credentials.to_json().encode()).decode()
    with Session(engine) as db:
        lock_calendar(db, user.id)
        record = db.get(GoogleConnection, user.id)
        if record:
            record.credentials_ciphertext = encrypted
            record.revision += 1
        else:
            record = GoogleConnection(user_id=user.id, credentials_ciphertext=encrypted)
        db.add(record)
        db.commit()


def get_gcal_credentials(user):
    with Session(engine) as db:
        record = db.get(GoogleConnection, user.id)
        if record is None:
            return None
        encrypted, revision = record.credentials_ciphertext, record.revision
    creds = Credentials.from_authorized_user_info(json.loads(cipher().decrypt(encrypted.encode())))
    if not creds.valid and creds.expired and creds.refresh_token:
        request = Request()
        creds.refresh(lambda *args, **kwargs: request(*args, **{**kwargs, "timeout": 10}))
        with Session(engine) as db:
            row = db.exec(
                select(GoogleConnection).where(GoogleConnection.user_id == user.id).with_for_update()
            ).first()
            if row and row.revision == revision:
                row.credentials_ciphertext = cipher().encrypt(creds.to_json().encode()).decode()
                db.add(row)
                db.commit()
    return creds if creds.valid else None


def get_calendar_service(user):
    creds = get_gcal_credentials(user)
    if not creds:
        return None
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp

    return build(
        "calendar", "v3", http=AuthorizedHttp(creds, http=httplib2.Http(timeout=10)), cache_discovery=False
    )


def get_managed_calendar_id(service, user=None, *, create=False):
    if user:
        with Session(engine) as db:
            row = db.get(GoogleConnection, user.id)
            if row and row.managed_calendar_id:
                return row.managed_calendar_id
    name = os.getenv("GOOGLE_MANAGED_CALENDAR_NAME", "Predestination")
    page_token, calendar_id = None, None
    while True:
        page = service.calendarList().list(pageToken=page_token).execute()
        calendar_id = next((c["id"] for c in page.get("items", []) if c.get("summary") == name), None)
        page_token = page.get("nextPageToken")
        if calendar_id or not page_token:
            break
    if not calendar_id:
        if not create:
            raise ValueError("Google managed-calendar setup is still pending; retry shortly")
        calendar_id = service.calendars().insert(body={"summary": name}).execute()["id"]
    if user:
        with Session(engine) as db:
            row = db.get(GoogleConnection, user.id)
            if row:
                row.managed_calendar_id = calendar_id
                db.add(row)
                db.commit()
    return calendar_id


def disconnect_google(session, user):
    owner = lock_calendar(session, user.id)
    for block in session.exec(select(Block).where(Block.user_id == user.id, Block.is_gcal == True)).all():
        session.delete(block)
    for row in session.exec(select(GoogleEventMapping).where(GoogleEventMapping.user_id == user.id)).all():
        session.delete(row)
    for job in session.exec(
        select(SyncJob).where(SyncJob.user_id == user.id, SyncJob.status.in_(["queued", "running", "failed"]))
    ).all():
        job.status = "cancelled"
        session.add(job)
    record = session.get(GoogleConnection, user.id)
    if record:
        session.delete(record)
    changed(session, owner)
    session.commit()


def _event_blocks(event: dict, cal_id: str, zone: ZoneInfo) -> list[dict]:
    if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
        return []
    label = event.get("summary") or "Busy (Google)"
    color = "#4285F4" if cal_id == "primary" else "#7c6aff"
    common = {"label": label, "color": color, "repeatDays": [], "is_gcal": True}
    if "date" in event.get("start", {}) and "date" in event.get("end", {}):
        first, last = date.fromisoformat(event["start"]["date"]), date.fromisoformat(event["end"]["date"])
        if not 0 < (last - first).days <= 366:
            raise ValueError("Google all-day interval is invalid or exceeds 366 days")
        return [
            {**common, "date": (first + timedelta(days=n)).isoformat(), "start": "00:00", "end": "24:00"}
            for n in range((last - first).days)
        ]
    if "dateTime" not in event.get("start", {}) or "dateTime" not in event.get("end", {}):
        return []

    def instant(value):
        dt = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
        return (
            dt.replace(tzinfo=ZoneInfo(value.get("timeZone", zone.key))) if dt.tzinfo is None else dt
        ).astimezone(timezone.utc)

    first, last = instant(event["start"]), instant(event["end"])
    if last <= first or (last - first).days > 366:
        raise ValueError("Google event interval is invalid")
    result, cursor = [], first
    while cursor < last:
        local = cursor.astimezone(zone)
        midnight = datetime.combine(local.date() + timedelta(days=1), day_time.min, zone).astimezone(
            timezone.utc
        )
        finish = min(last, midnight)
        local_end = finish.astimezone(zone)
        begin_min = local.hour * 60 + local.minute
        end_min = (
            1440
            if finish == midnight
            else local_end.hour * 60
            + local_end.minute
            + (1 if local_end.second or local_end.microsecond else 0)
        )
        if end_min <= begin_min:
            # A fall-back event can end at an earlier wall time. Preserve exact UTC
            # instants and conservatively display the repeated hour as busy.
            begin_min = min(begin_min, local_end.hour * 60)
            end_min = max(end_min, (local.hour + 1) * 60)
        result.append(
            {
                **common,
                "date": local.date().isoformat(),
                "start": f"{begin_min // 60:02d}:{begin_min % 60:02d}",
                "end": f"{end_min // 60:02d}:{end_min % 60:02d}",
                "starts_at": cursor.isoformat(),
                "ends_at": finish.isoformat(),
            }
        )
        cursor = finish
    return result


def sync_gcal_events(session, user, force=False, start=None, end=None):
    from app.integrations.google_sync import import_availability

    return import_availability(session, user, force, start, end)
