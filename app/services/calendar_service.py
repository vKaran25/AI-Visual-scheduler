import base64
import hashlib
import hmac
import logging
import os
import pickle
import time
from datetime import date, datetime, time as day_time, timedelta, timezone
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlmodel import Session, select

from app.core.config import APP_BASE_URL, GOOGLE_CALENDAR_TIMEZONE, JWT_SECRET_KEY
from app.db.models import Block, User
from app.services import scheduler_service

GOOGLE_TOKEN_DIR = os.getenv("GOOGLE_TOKEN_DIR") or "data/google_tokens"
os.makedirs(GOOGLE_TOKEN_DIR, exist_ok=True)
GCAL_CACHE_DURATION = 300
GOOGLE_IMPORT_SOURCE = "google_import"
logger = logging.getLogger(__name__)
last_gcal_sync_time_by_user = {}


def token_path(user: User) -> str:
    return os.path.join(GOOGLE_TOKEN_DIR, f"user_{user.id}.pickle")


def get_google_redirect_uri():
    return os.getenv("GOOGLE_OAUTH_REDIRECT_URI") or f"{APP_BASE_URL}/api/google/oauth/callback"


def get_client_config():
    redirect_uri = get_google_redirect_uri()
    return {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "project_id": "scheduler-app",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uris": [redirect_uri],
        }
    }


def get_gcal_credentials(user: User):
    path = token_path(user)
    if os.path.exists(path):
        with open(path, "rb") as token:
            creds = pickle.load(token)
            if creds and creds.valid:
                return creds
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(path, "wb") as refreshed:
                    pickle.dump(creds, refreshed)
                return creds
    return None


def get_calendar_service(user: User):
    creds = get_gcal_credentials(user)
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)


def _code_verifier(state: str) -> str:
    # Reconstruct the PKCE verifier on the callback in any worker without storing it.
    digest = hmac.new(JWT_SECRET_KEY.encode(), state.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def create_oauth_flow(state=None):
    flow = Flow.from_client_config(get_client_config(), scopes=["https://www.googleapis.com/auth/calendar"],
                                   state=state, code_verifier=_code_verifier(state) if state else None)
    flow.redirect_uri = get_google_redirect_uri()
    return flow


def build_authorization_url(state=None):
    flow = create_oauth_flow(state=state)
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline", state=state)
    return auth_url, state, getattr(flow, "code_verifier", None)


def save_callback_credentials(user: User, authorization_response, state=None, code_verifier=None):
    flow = create_oauth_flow(state=state)
    flow.fetch_token(authorization_response=authorization_response,
                     code_verifier=code_verifier or (_code_verifier(state) if state else flow.code_verifier))
    with open(token_path(user), "wb") as token:
        pickle.dump(flow.credentials, token)


def disconnect_google(session: Session, user: User):
    path = token_path(user)
    if os.path.exists(path):
        os.remove(path)
    _delete_imported_blocks(session, user)
    session.commit()
    last_gcal_sync_time_by_user[user.id] = 0


def get_managed_calendar_id(service):
    cal_name = os.getenv("GOOGLE_MANAGED_CALENDAR_NAME", "Predestination Plans")
    page_token = None
    while True:
        calendar_list = service.calendarList().list(pageToken=page_token).execute()
        for entry in calendar_list["items"]:
            if entry["summary"] == cal_name:
                return entry["id"]
        page_token = calendar_list.get("nextPageToken")
        if not page_token:
            break
    created = service.calendars().insert(body={"summary": cal_name}).execute()
    return created["id"]


def _delete_imported_blocks(session: Session, user: User) -> None:
    # is_gcal was also used for exported local plans; never delete by that flag alone.
    imported = session.exec(select(Block).where(
        Block.user_id == user.id, Block.is_gcal == True
    )).all()
    for block in imported:
        # Older imports were untagged, while exported agent plans have a session ID.
        if block.preset_source == GOOGLE_IMPORT_SOURCE or block.session_id is None:
            session.delete(block)


def _event_blocks(event: dict, cal_id: str, zone: ZoneInfo) -> list[dict]:
    if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
        return []
    if "date" in event.get("start", {}) and "date" in event.get("end", {}):
        # Google's all-day end date is exclusive.
        first = date.fromisoformat(event["start"]["date"])
        last = date.fromisoformat(event["end"]["date"])
        if last <= first:
            raise ValueError("Google all-day event ends before it starts")
        return [{"date": (first + timedelta(days=offset)).isoformat(), "start": "00:00", "end": "24:00",
                 "label": event.get("summary") or "Busy (Google)", "color": "#4285F4" if cal_id == "primary" else "#7c6aff",
                 "repeatDays": [], "is_gcal": True}
                for offset in range((last - first).days)]
    if "dateTime" not in event.get("start", {}) or "dateTime" not in event.get("end", {}):
        return []

    def local_dt(value: dict) -> datetime:
        dt = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
        source_zone = ZoneInfo(value.get("timeZone", GOOGLE_CALENDAR_TIMEZONE))
        return (dt.replace(tzinfo=source_zone) if dt.tzinfo is None else dt).astimezone(zone)

    start = local_dt(event["start"])
    end = local_dt(event["end"])
    if end <= start:
        raise ValueError("Google event ends before it starts")
    blocks = []
    cursor = start
    while cursor.date() < end.date():
        blocks.append((cursor.date().isoformat(), cursor.strftime("%H:%M"), "24:00"))
        cursor = datetime.combine(cursor.date() + timedelta(days=1), day_time.min, zone)
    if end > cursor:
        blocks.append((cursor.date().isoformat(), cursor.strftime("%H:%M"), end.strftime("%H:%M")))
    return [{"date": date, "start": first, "end": last, "label": event.get("summary") or "Busy (Google)",
             "color": "#4285F4" if cal_id == "primary" else "#7c6aff", "repeatDays": [], "is_gcal": True}
            for date, first, last in blocks if first != last]


def sync_gcal_events(session: Session, user: User, force=False):
    last = last_gcal_sync_time_by_user.get(user.id, 0)
    if not force and time.time() - last < GCAL_CACHE_DURATION:
        return True
    blocks = []
    try:
        service = get_calendar_service(user)
        if not service:
            return False
        zone = ZoneInfo(GOOGLE_CALENDAR_TIMEZONE)
        now = datetime.now(timezone.utc)
        # Include yesterday's starts so ongoing overnight events appear today.
        window = {"timeMin": (now - timedelta(days=1)).isoformat(),
                  "timeMax": (now + timedelta(days=scheduler_service.MAX_SEARCH_DAYS)).isoformat(),
                  "singleEvents": True, "orderBy": "startTime"}
        managed_cal_id = get_managed_calendar_id(service)
        for cal_id in dict.fromkeys(("primary", managed_cal_id)):
            page_token = None
            while True:
                page = service.events().list(calendarId=cal_id, pageToken=page_token, **window).execute()
                for event in page.get("items", []):
                    private = event.get("extendedProperties", {}).get("private", {})
                    if cal_id == managed_cal_id and private.get("scheduler_user_id") == str(user.id):
                        continue  # The local confirmed block is already in the scheduler.
                    blocks.extend(_event_blocks(event, cal_id, zone))
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
    except Exception:
        logger.exception("Google calendar sync failed for user %s; keeping existing imports", user.id)
        return False

    try:
        _delete_imported_blocks(session, user)
        session.flush()
        for data in blocks:
            scheduler_service.create_block(session, user, data, skip_overlap=True,
                                           preset_source=GOOGLE_IMPORT_SOURCE, commit=False)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Google calendar import failed for user %s; keeping existing imports", user.id)
        return False
    last_gcal_sync_time_by_user[user.id] = time.time()
    return True


def insert_calendar_event(user: User, block):
    service = get_calendar_service(user)
    managed_cal_id = get_managed_calendar_id(service) if service else None
    if not service or not managed_cal_id:
        return False
    zone = ZoneInfo(GOOGLE_CALENDAR_TIMEZONE)
    day = datetime.fromisoformat(block.date).date()
    start = datetime.combine(day, day_time.min, zone) + timedelta(minutes=block.start_minutes)
    end = datetime.combine(day, day_time.min, zone) + timedelta(minutes=block.end_minutes)
    service.events().insert(calendarId=managed_cal_id, body={
        "summary": block.label,
        "start": {"dateTime": start.isoformat(), "timeZone": GOOGLE_CALENDAR_TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": GOOGLE_CALENDAR_TIMEZONE},
        "extendedProperties": {"private": {"scheduler_user_id": str(user.id), "scheduler_block_id": str(block.id)}},
    }).execute()
    return True

