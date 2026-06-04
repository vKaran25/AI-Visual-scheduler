import os
import pickle
import time
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlmodel import Session

from app.core.config import APP_BASE_URL
from app.db.models import User
from app.services import scheduler_service

GOOGLE_TOKEN_DIR = os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens")
os.makedirs(GOOGLE_TOKEN_DIR, exist_ok=True)
GCAL_CACHE_DURATION = 300
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


def create_oauth_flow(state=None):
    flow = Flow.from_client_config(get_client_config(), scopes=["https://www.googleapis.com/auth/calendar"], state=state)
    flow.redirect_uri = get_google_redirect_uri()
    return flow


def build_authorization_url():
    flow = create_oauth_flow()
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    return auth_url, state, getattr(flow, "code_verifier", None)


def save_callback_credentials(user: User, authorization_response, state=None, code_verifier=None):
    flow = create_oauth_flow(state=state)
    if code_verifier:
        flow.fetch_token(authorization_response=authorization_response, code_verifier=code_verifier)
    else:
        flow.fetch_token(authorization_response=authorization_response)
    with open(token_path(user), "wb") as token:
        pickle.dump(flow.credentials, token)


def disconnect_google(session: Session, user: User):
    path = token_path(user)
    if os.path.exists(path):
        os.remove(path)
    scheduler_service.delete_blocks_by_flags(session, user, is_gcal=True)
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


def sync_gcal_events(session: Session, user: User, force=False):
    last = last_gcal_sync_time_by_user.get(user.id, 0)
    if not force and time.time() - last < GCAL_CACHE_DURATION:
        return
    service = get_calendar_service(user)
    if not service:
        return
    scheduler_service.delete_blocks_by_flags(session, user, is_gcal=True)
    now = datetime.utcnow().isoformat() + "Z"
    end = (datetime.utcnow() + timedelta(days=scheduler_service.MAX_SEARCH_DAYS)).isoformat() + "Z"
    managed_cal_id = get_managed_calendar_id(service)
    for cal_id in ["primary", managed_cal_id]:
        try:
            events = service.events().list(calendarId=cal_id, timeMin=now, timeMax=end, singleEvents=True, orderBy="startTime").execute()
            for event in events.get("items", []):
                sdt = event["start"].get("dateTime", event["start"].get("date"))
                edt = event["end"].get("dateTime", event["end"].get("date"))
                if "T" not in sdt:
                    continue
                st_dt = datetime.fromisoformat(sdt)
                end_dt = datetime.fromisoformat(edt)
                end_time = end_dt.strftime("%H:%M")
                if end_dt.hour == 0 and end_dt.minute == 0 and end_dt.date() > st_dt.date():
                    end_time = "24:00"
                scheduler_service.create_block(
                    session,
                    user,
                    {
                        "date": st_dt.strftime("%Y-%m-%d"),
                        "start": st_dt.strftime("%H:%M"),
                        "end": end_time,
                        "label": event.get("summary", "Busy (Google)"),
                        "color": "#4285F4" if cal_id == "primary" else "#7c6aff",
                        "repeatDays": [],
                        "is_gcal": True,
                    },
                    skip_overlap=True,
                )
        except Exception as exc:
            print("GCal fetch error for", cal_id, exc)
    last_gcal_sync_time_by_user[user.id] = time.time()


def insert_calendar_event(user: User, block):
    service = get_calendar_service(user)
    managed_cal_id = get_managed_calendar_id(service) if service else None
    if not service or not managed_cal_id:
        return False
    timezone_str = datetime.now().astimezone().strftime("%z")
    tzinfo_formatted = f"{timezone_str[:3]}:{timezone_str[3:]}"
    st_dt = f"{block.date}T{block.start}:00{tzinfo_formatted}"
    end_dt = f"{block.date}T{block.end}:00{tzinfo_formatted}"
    service.events().insert(calendarId=managed_cal_id, body={
        "summary": block.label,
        "start": {"dateTime": st_dt},
        "end": {"dateTime": end_dt},
    }).execute()
    return True

