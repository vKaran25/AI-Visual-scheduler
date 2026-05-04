import os
import time
import pickle
from datetime import datetime, timedelta
from typing import Optional, List, Union
from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from google import genai as google_genai
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Predestination Scheduler API")
templates = Jinja2Templates(directory=".")
os.environ['OAUTHLIB_INSPECURE_TRANSPORT'] = '1'

busy_slots = [
    {
        'id': -1,
        'date': None,
        'start': '00:00',
        'end': '06:00',
        'startMinutes': 0,
        'endMinutes': 360,
        'label': 'Sleep',
        'color': '#4527a0',
        'repeatDays': [0, 1, 2, 3, 4, 5, 6],
        'is_gcal': False
    },
    {
        'id': -2,
        'date': None,
        'start': '08:30',
        'end': '17:00',
        'startMinutes': 510,
        'endMinutes': 1020,
        'label': 'Classes',
        'color': '#2e7d32',
        'repeatDays': [0, 1, 2, 3, 4],
        'is_gcal': False
    }
]
_counter = 1
MAX_SEARCH_DAYS = 60
last_gcal_sync_time = 0
GCAL_CACHE_DURATION = 300

GOOGLE_TOKEN_DIR = os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens")
os.makedirs(GOOGLE_TOKEN_DIR, exist_ok=True)
TOKEN_PATH = os.path.join(GOOGLE_TOKEN_DIR, "token.pickle")

ENABLE_TOOLS = os.getenv("ENABLE_LLM_TOOL_CALLING", "true").lower() == "true"


def time_to_minutes(t: str) -> int:
    h, m = map(int, t.split(':'))
    return h * 60 + m

def minutes_to_time(mins: int) -> str:
    if mins <= 0: return '00:00'
    if mins >= 1440: return '24:00'
    return f'{mins // 60:02d}:{mins % 60:02d}'

def merge_slots(slots):
    if not slots: return []
    s = sorted(slots, key=lambda x: x[0])
    merged = [list(s[0])]
    for start, end in s[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(x) for x in merged]

def normalize_repeat_days(days):
    if not days: return []
    return sorted({int(d) for d in days if 0 <= int(d) <= 6})

def slots_for_date(date_str: str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    dow = dt.weekday()
    out = []
    for s in busy_slots:
        repeat_days = s.get('repeatDays', [])
        if repeat_days:
            if dow in repeat_days: out.append({**s, 'date': date_str})
        elif s.get('date') == date_str:
            out.append(s)
    return out

def compute_free_blocks(start_dt_str: str, total_hours: float, max_days: int = MAX_SEARCH_DAYS):
    start_dt = datetime.fromisoformat(start_dt_str)
    total_minutes = max(0, round(total_hours * 60))
    total_minutes = round(total_minutes / 5) * 5
    allocated = []
    remaining = total_minutes
    current_dt = start_dt

    for _ in range(max_days):
        if remaining <= 0: break
        date_str = current_dt.strftime('%Y-%m-%d')
        start_min = current_dt.hour * 60 + current_dt.minute if current_dt.date() == start_dt.date() else 0
        rem = start_min % 5
        if rem != 0: start_min += (5 - rem)
        
        merged_busy = merge_slots([(s['startMinutes'], s['endMinutes']) for s in slots_for_date(date_str)])

        free_gaps = []
        cursor = start_min
        for bstart, bend in merged_busy:
            if bend <= cursor: continue
            if bstart > cursor:
                gs, ge = cursor, bstart
                rm = gs % 5
                if rm != 0: gs += (5 - rm)
                ge -= (ge % 5)
                if ge - gs >= 15:
                    free_gaps.append((gs, ge))
            cursor = max(cursor, bend)
            
        if cursor < 1440:
            gs, ge = cursor, 1440
            rm = gs % 5
            if rm != 0: gs += (5 - rm)
            ge -= (ge % 5)
            if ge - gs >= 15:
                free_gaps.append((gs, ge))

        for gstart, gend in free_gaps:
            if remaining <= 0: break
            available = gend - gstart
            if available <= 0: continue
            use = min(available, remaining)
            dh, dm = divmod(use, 60)
            duration_str = f'{dh}h {dm}m' if dh and dm else f'{dh}h' if dh else f'{dm}m'
            allocated.append({
                'date': date_str,
                'start': minutes_to_time(gstart),
                'end': minutes_to_time(gstart + use),
                'startMinutes': gstart,
                'endMinutes': gstart + use,
                'duration': use / 60,
                'durationStr': duration_str,
            })
            remaining -= use

        next_day = (current_dt + timedelta(days=1)).date()
        current_dt = datetime(next_day.year, next_day.month, next_day.day)

    return {
        'allocated': allocated,
        'totalAllocated': (total_minutes - remaining) / 60,
        'requested': total_hours,
        'fulfilled': remaining <= 0,
        'missing': remaining / 60,
    }


def get_gcal_credentials():
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)
            if creds and creds.valid: return creds
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(GoogleRequest())
                with open(TOKEN_PATH, 'wb') as token:
                    pickle.dump(creds, token)
                return creds
    return None

def get_calendar_service():
    creds = get_gcal_credentials()
    if not creds: return None
    return build('calendar', 'v3', credentials=creds)

def get_managed_calendar_id(service):
    cal_name = os.getenv('GOOGLE_MANAGED_CALENDAR_NAME', 'Predestination Plans')
    page_token = None
    while True:
        calendar_list = service.calendarList().list(pageToken=page_token).execute()
        for calendar_list_entry in calendar_list['items']:
            if calendar_list_entry['summary'] == cal_name:
                return calendar_list_entry['id']
        page_token = calendar_list.get('nextPageToken')
        if not page_token: break
    created_calendar = service.calendars().insert(body={'summary': cal_name}).execute()
    return created_calendar['id']

def sync_gcal_events(force=False):
    global busy_slots, _counter, last_gcal_sync_time

    if not force and time.time() - last_gcal_sync_time < GCAL_CACHE_DURATION:
        return

    service = get_calendar_service()
    if not service: return

    busy_slots = [s for s in busy_slots if not s.get('is_gcal', False)]

    now = datetime.utcnow().isoformat() + 'Z'
    end = (datetime.utcnow() + timedelta(days=MAX_SEARCH_DAYS)).isoformat() + 'Z'

    managed_cal_id = get_managed_calendar_id(service)
    cals_to_sync = ['primary', managed_cal_id]

    for cal_id in cals_to_sync:
        try:
            events_result = service.events().list(calendarId=cal_id, timeMin=now, timeMax=end,
                                          singleEvents=True, orderBy='startTime').execute()
            for event in events_result.get('items', []):
                sdt = event['start'].get('dateTime', event['start'].get('date'))
                edt = event['end'].get('dateTime', event['end'].get('date'))
                if 'T' not in sdt: continue

                st_dt = datetime.fromisoformat(sdt)
                end_dt = datetime.fromisoformat(edt)

                start_m = st_dt.hour * 60 + st_dt.minute
                end_m = end_dt.hour * 60 + end_dt.minute
                if end_m == 0 and end_dt.date() > st_dt.date(): end_m = 1440

                slot = {
                    'id': _counter,
                    'date': st_dt.strftime('%Y-%m-%d'),
                    'start': st_dt.strftime('%H:%M'),
                    'end': end_dt.strftime('%H:%M'),
                    'startMinutes': start_m,
                    'endMinutes': end_m,
                    'label': event.get('summary', 'Busy (Google)'),
                    'color': '#4285F4' if cal_id == 'primary' else '#7c6aff',
                    'repeatDays': [],
                    'is_gcal': True
                }
                busy_slots.append(slot)
                _counter += 1
        except Exception as e:
            print("GCal fetch error for", cal_id, e)

    last_gcal_sync_time = time.time()


class AddSlotRequest(BaseModel):
    start: str
    end: str
    label: Optional[str] = "Busy"
    color: Optional[str] = "#d81b60"
    repeatDays: Optional[List[int]] = None
    date: Optional[str] = None


class PutSlotRequest(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    label: Optional[str] = None
    color: Optional[str] = None
    date: Optional[str] = None
    repeatDays: Optional[List[int]] = None


class ChatRequest(BaseModel):
    prompt: str
    slack: float = 0.0
    start_after: Optional[str] = None
    session_id: Optional[str] = None


class AcceptRequest(BaseModel):
    session_id: str


class RejectRequest(BaseModel):
    session_id: str


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html", "r") as f:
        return f.read()


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/google/status")
async def google_status():
    return {"connected": get_gcal_credentials() is not None}


@app.post("/api/google/oauth/logout")
async def google_logout():
    global busy_slots, last_gcal_sync_time
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
    busy_slots = [s for s in busy_slots if not s.get('is_gcal', False)]
    last_gcal_sync_time = 0
    return {"success": True}


@app.get("/api/google/oauth/login")
async def google_login():
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "project_id": "scheduler-app",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uris": [os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/google/oauth/callback")]
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    flow.redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline')
    return RedirectResponse(url=auth_url)


@app.get("/api/google/oauth/callback")
async def google_callback(state: Optional[str] = None, code: Optional[str] = None, error: Optional[str] = None):
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "project_id": "scheduler-app",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uris": [os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/google/oauth/callback")]
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=['https://www.googleapis.com/auth/calendar'],
        state=state
    )
    flow.redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")

    if code:
        flow.fetch_token(code=code)
        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(flow.credentials, token)

        sync_gcal_events()

    return HTMLResponse(content="<script>window.opener ? window.close() : window.location.href='/';</script>")


@app.post("/api/chat")
async def handle_chat(req: ChatRequest):
    from agent import run_planner, get_pending_blocks
    
    session_id = req.session_id or str(int(time.time() * 1000))

    result = run_planner(
        prompt=req.prompt,
        session_id=session_id,
        user_id="default_user"
    )

    pending = get_pending_blocks(session_id)

    return {
        "response": result.get("response", ""),
        "scheduled": pending,
        "session_id": session_id
    }


@app.post("/api/chat/accept")
async def accept_chat(req: AcceptRequest):
    from agent import get_pending_blocks
    
    session_id = req.session_id
    service = get_calendar_service()
    managed_cal_id = get_managed_calendar_id(service) if service else None

    accepted = 0
    for slot in busy_slots:
        if slot.get('session_id') == session_id and slot.get('is_pending'):
            slot['is_pending'] = False
            if service and managed_cal_id:
                slot['is_gcal'] = True
            accepted += 1

            if service and managed_cal_id:
                try:
                    timezone_str = datetime.now().astimezone().strftime('%z')
                    tzinfo_formatted = f"{timezone_str[:3]}:{timezone_str[3:]}"
                    st_dt = f"{slot['date']}T{slot['start']}:00{tzinfo_formatted}"
                    end_dt = f"{slot['date']}T{slot['end']}:00{tzinfo_formatted}"
                    service.events().insert(calendarId=managed_cal_id, body={
                        'summary': slot['label'],
                        'start': {'dateTime': st_dt},
                        'end': {'dateTime': end_dt},
                    }).execute()
                except Exception as ex:
                    print("Failed to sync new event to GCAL", ex)

    return {
        "success": True,
        "count": accepted,
        "pending_blocks": get_pending_blocks(session_id)
    }


@app.post("/api/chat/reject")
async def reject_chat(req: RejectRequest):
    global busy_slots
    session_id = req.session_id
    busy_slots = [s for s in busy_slots if s.get('session_id') != session_id]
    return {"success": True}


@app.get("/api/slots")
async def get_slots(date: Optional[str] = None):
    sync_gcal_events()
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')
    return slots_for_date(date)


@app.post("/api/slots")
async def add_slot(req: AddSlotRequest):
    global _counter
    start, end = req.start, req.end
    if not start or not end:
        raise HTTPException(status_code=400, detail="Start and end are required")
    if time_to_minutes(end) <= time_to_minutes(start):
        raise HTTPException(status_code=400, detail="End must be after start")

    slot = {
        'id': _counter,
        'date': None if req.repeatDays else req.date,
        'start': start,
        'end': end,
        'startMinutes': time_to_minutes(start),
        'endMinutes': time_to_minutes(end),
        'label': req.label,
        'color': req.color,
        'repeatDays': normalize_repeat_days(req.repeatDays or []),
    }
    busy_slots.append(slot)
    _counter += 1
    return slot


@app.put("/api/slots/{slot_id}")
async def update_slot(slot_id: int, req: PutSlotRequest):
    global busy_slots
    slot = next((s for s in busy_slots if s['id'] == slot_id), None)
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    
    start = req.start if req.start else slot['start']
    end = req.end if req.end else slot['end']
    if time_to_minutes(end) <= time_to_minutes(start):
        raise HTTPException(status_code=400, detail="Invalid times")

    slot.update({
        'date': req.date if req.date else slot.get('date'),
        'start': start, 'end': end,
        'startMinutes': time_to_minutes(start), 'endMinutes': time_to_minutes(end),
        'label': req.label if req.label else slot['label'],
        'color': req.color if req.color else slot['color'],
        'repeatDays': normalize_repeat_days(req.repeatDays if req.repeatDays else slot.get('repeatDays'))
    })
    return slot


@app.delete("/api/slots/{slot_id}")
async def delete_slot(slot_id: int):
    global busy_slots
    busy_slots = [s for s in busy_slots if s['id'] != slot_id]
    return {"success": True}


@app.get("/api/free")
async def get_free(start_dt: Optional[str] = None, hours: float = 1.0):
    sync_gcal_events()
    if not start_dt:
        start_dt = datetime.now().isoformat(timespec='minutes')
    return compute_free_blocks(start_dt, hours)


if __name__ == '__main__':
    import uvicorn
    sync_gcal_events()
    uvicorn.run(app, host="0.0.0.0", port=8000)