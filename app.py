import os
import time
import json
import pickle
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import google.generativeai as genai

load_dotenv()

app = Flask(__name__, template_folder='.')
app.secret_key = 'super_secret_key_timeblocks'
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

busy_slots = []
_counter = 0
MAX_SEARCH_DAYS = 60
last_gcal_sync_time = 0
GCAL_CACHE_DURATION = 300

GOOGLE_TOKEN_DIR = os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens")
os.makedirs(GOOGLE_TOKEN_DIR, exist_ok=True)
TOKEN_PATH = os.path.join(GOOGLE_TOKEN_DIR, "token.pickle")

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
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
    allocated = []
    remaining = total_minutes
    current_dt = start_dt

    for _ in range(max_days):
        if remaining <= 0: break
        date_str = current_dt.strftime('%Y-%m-%d')
        start_min = current_dt.hour * 60 + current_dt.minute if current_dt.date() == start_dt.date() else 0
        merged_busy = merge_slots([(s['startMinutes'], s['endMinutes']) for s in slots_for_date(date_str)])
        
        free_gaps = []
        cursor = start_min
        for bstart, bend in merged_busy:
            if bend <= cursor: continue
            if bstart > cursor: free_gaps.append((cursor, bstart))
            cursor = max(cursor, bend)
        if cursor < 1440: free_gaps.append((cursor, 1440))

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


# ---- Google Calendar Functions ----

def get_gcal_credentials():
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)
            if creds and creds.valid: return creds
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
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
    
    # Retain non-gcal manual slots
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
                if 'T' not in sdt: continue  # Skip all-day events for now
                
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

@app.route('/api/google/status', methods=['GET'])
def google_status():
    return jsonify({"connected": get_gcal_credentials() is not None})

@app.route('/api/google/oauth/logout', methods=['POST'])
def google_logout():
    global busy_slots, last_gcal_sync_time
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
    busy_slots = [s for s in busy_slots if not s.get('is_gcal', False)]
    last_gcal_sync_time = 0
    return jsonify({"success": True})

@app.route('/api/google/oauth/login')
def google_login():
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
    session['state'] = state
    # Save the PKCE Code Verifier
    if hasattr(flow, 'code_verifier'):
        session['code_verifier'] = getattr(flow, 'code_verifier')
    return redirect(auth_url)

@app.route('/api/google/oauth/callback')
def google_callback():
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
        state=request.args.get('state')
    )
    flow.redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    
    code_verifier = session.get('code_verifier')
    if code_verifier:
        flow.fetch_token(authorization_response=request.url, code_verifier=code_verifier)
    else:
        flow.fetch_token(authorization_response=request.url)
    
    with open(TOKEN_PATH, 'wb') as token:
        pickle.dump(flow.credentials, token)
        
    sync_gcal_events()
    return "<script>window.opener ? window.close() : window.location.href='/';</script>"

# ---- Gemini API Logic ----

@app.route('/api/chat', methods=['POST'])
def handle_chat():
    d = request.json or {}
    prompt = d.get('prompt')
    slack = float(d.get('slack', 0.0))
    
    system_instruction = f"""
    You are an AI task scheduler assistant. 
    1. Read the user's task.
    2. Break it down into clear steps in hours. Each step MUST have a title and duration_hours.
    3. Return ONLY a pure JSON array of objects. NO markdown formatting, NO backticks.
    Format exactly like this:
    [
        {{"title": "Step 1", "duration_hours": 1.5}},
        {{"title": "Step 2", "duration_hours": 0.5}}
    ]
    Do not add any other text.
    """
    
    gemini_model = genai.GenerativeModel(
        model_name=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        system_instruction=system_instruction
    )
    
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith('```json'): text = text[7:]
        if text.startswith('```'): text = text[3:]
        if text.endswith('```'): text = text[:-3]
        
        steps = json.loads(text.strip())
        
        sync_gcal_events()
        
        service = get_calendar_service()
        managed_cal_id = get_managed_calendar_id(service) if service else None
        
        search_start_dt = datetime.now()
        scheduled_events = []
        global _counter
        
        for step in steps:
            title = step.get('title', 'AI Step')
            raw_duration = float(step.get('duration_hours', 1.0))
            slacked_duration = raw_duration * (1.0 + slack)
            
            free_res = compute_free_blocks(search_start_dt.isoformat()[:16], slacked_duration)
            allocated = free_res.get('allocated', [])
            
            for block in allocated:
                d_str = block['date']
                s_str = block['start']
                e_str = block['end']
                
                slot = {
                    'id': _counter,
                    'date': d_str,
                    'start': s_str,
                    'end': e_str,
                    'startMinutes': time_to_minutes(s_str),
                    'endMinutes': time_to_minutes(e_str),
                    'label': title,
                    'color': '#7c6aff',
                    'repeatDays': [],
                    'is_gcal': True if managed_cal_id else False
                }
                busy_slots.append(slot)
                _counter += 1
                scheduled_events.append(slot)
                
                if service and managed_cal_id:
                    try:
                        timezone_str = datetime.now().astimezone().strftime('%z')
                        tzinfo_formatted = f"{timezone_str[:3]}:{timezone_str[3:]}"
                        st_dt = f"{d_str}T{s_str}:00{tzinfo_formatted}"
                        end_dt = f"{d_str}T{e_str}:00{tzinfo_formatted}"
                        service.events().insert(calendarId=managed_cal_id, body={
                            'summary': title,
                            'start': {'dateTime': st_dt},
                            'end': {'dateTime': end_dt},
                        }).execute()
                    except Exception as ex:
                        print("Failed to sync new event to GCAL", ex)
            
            if allocated:
                last_block = allocated[-1]
                search_start_dt = datetime.strptime(f"{last_block['date']} {last_block['end']}", "%Y-%m-%d %H:%M")
        
        friendly_text = f"Successfully scheduled {len(steps)} steps!\n\n"
        for ev in scheduled_events:
            friendly_text += f"- **{ev['label']}**: {ev['date']} {ev['start']} - {ev['end']}\n"
            
        return jsonify({"response": friendly_text, "scheduled": scheduled_events})
    except Exception as e:
        print("Gemini/Scheduling error:", e)
        return jsonify({"error": "Failed to schedule: " + str(e)}), 500


# ---- Standard Routes ----

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/slots', methods=['GET'])
def get_slots():
    sync_gcal_events() # refresh before sending
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    return jsonify(slots_for_date(date))

@app.route('/api/slots', methods=['POST'])
def add_slot():
    global _counter
    d = request.json or {}
    start, end = d.get('start'), d.get('end')
    if not start or not end: return jsonify({'error': 'Start and end are required'}), 400
    if time_to_minutes(end) <= time_to_minutes(start): return jsonify({'error': 'End must be after start'}), 400
    
    slot = {
        'id': _counter,
        'date': None if d.get('repeatDays') else d.get('date'),
        'start': start,
        'end': end,
        'startMinutes': time_to_minutes(start),
        'endMinutes': time_to_minutes(end),
        'label': d.get('label', 'Busy'),
        'color': d.get('color', '#d81b60'),
        'repeatDays': normalize_repeat_days(d.get('repeatDays', [])),
    }
    busy_slots.append(slot)
    _counter += 1
    return jsonify(slot), 201

@app.route('/api/slots/<int:slot_id>', methods=['PUT'])
def update_slot(slot_id):
    slot = next((s for s in busy_slots if s['id'] == slot_id), None)
    if not slot: return jsonify({'error': 'Not found'}), 404
    d = request.json or {}
    start, end = d.get('start', slot['start']), d.get('end', slot['end'])
    if time_to_minutes(end) <= time_to_minutes(start): return jsonify({'error': 'Invalid times'}), 400
    
    slot.update({
        'date': d.get('date', slot.get('date')),
        'start': start, 'end': end,
        'startMinutes': time_to_minutes(start), 'endMinutes': time_to_minutes(end),
        'label': d.get('label', slot['label']),
        'color': d.get('color', slot['color']),
        'repeatDays': normalize_repeat_days(d.get('repeatDays', slot.get('repeatDays')))
    })
    return jsonify(slot)

@app.route('/api/slots/<int:slot_id>', methods=['DELETE'])
def delete_slot(slot_id):
    global busy_slots
    busy_slots = [s for s in busy_slots if s['id'] != slot_id]
    return jsonify({'success': True})

@app.route('/api/free', methods=['GET'])
def get_free():
    sync_gcal_events()
    start_dt = request.args.get('start_dt', datetime.now().isoformat(timespec='minutes'))
    return jsonify(compute_free_blocks(start_dt, float(request.args.get('hours', 1))))

if __name__ == '__main__':
    sync_gcal_events()
    app.run(debug=True, port=8000)
