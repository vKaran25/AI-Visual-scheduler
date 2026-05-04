import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List
from google import genai
from agno.agent import Agent
from agno.team import Team
from agno.db.sqlite import SqliteDb
from agno.models.nvidia import Nvidia
from agno.tools.function import Function

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

MEMORY_DB_PATH = os.path.join(DATA_DIR, 'memory.db')
PREFERENCES_FILE = os.path.join(DATA_DIR, 'preferences.json')

memory_db = SqliteDb(
    db_file=MEMORY_DB_PATH,
    session_table="agent_memory"
)

agent_sessions_db = SqliteDb(
    db_file=MEMORY_DB_PATH,
    session_table="agent_sessions"
)

scheduler_db = SqliteDb(
    db_file=MEMORY_DB_PATH,
    session_table="scheduler_sessions"
)


def _load_preferences():
    if not os.path.exists(PREFERENCES_FILE):
        return []
    try:
        with open(PREFERENCES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_preferences(prefs):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PREFERENCES_FILE, 'w') as f:
        json.dump(prefs, f, indent=2)


def store_preference(category: str, preference: str) -> str:
    """Store a user preference in the preferences file."""
    prefs = _load_preferences()
    prefs.append({
        'category': category,
        'preference': preference,
        'created_at': datetime.now().isoformat()
    })
    _save_preferences(prefs)
    return f"Preference saved: [{category}] {preference}"


def retrieve_preferences(category: Optional[str] = None) -> str:
    """Retrieve all preferences, optionally filtered by category."""
    prefs = _load_preferences()
    if category:
        filtered = [p for p in prefs if p.get('category') == category]
    else:
        filtered = prefs

    if not filtered:
        return "No preferences found."

    lines = [f"- [{p['category']}] {p['preference']}" for p in filtered]
    return "Stored preferences:\n" + "\n".join(lines)


def delete_preference(preference_text: str) -> str:
    """Delete a preference by matching text (partial match)."""
    prefs = _load_preferences()
    original_count = len(prefs)
    prefs = [p for p in prefs if preference_text.lower() not in p.get('preference', '').lower()]

    if len(prefs) == original_count:
        return "Preference not found."

    _save_preferences(prefs)
    return f"Deleted preference containing: {preference_text}"


def find_free_time(start_datetime: str, hours_needed: float) -> str:
    """Find available time slots."""
    from main import compute_free_blocks, sync_gcal_events

    sync_gcal_events()

    try:
        start_dt = datetime.fromisoformat(start_datetime)
    except ValueError:
        start_dt = datetime.now()

    result = compute_free_blocks(start_dt.isoformat()[:16], hours_needed)
    allocated = result.get('allocated', [])

    if not allocated:
        hours_remaining = hours_needed - result.get('totalAllocated', 0)
        return f"No free time found. {hours_remaining:.1f}h remaining."

    lines = []
    for block in allocated:
        lines.append(f"- {block['date']} {block['start']}-{block['end']} ({block['durationStr']})")

    return "Available slots:\n" + "\n".join(lines)


def add_busy_block(date: str, start: str, end: str, label: str, session_id: str, color: str = '#7c6aff') -> str:
    """Add a busy time block to the schedule."""
    from main import busy_slots, _counter, time_to_minutes

    slot = {
        'id': _counter,
        'date': date,
        'start': start,
        'end': end,
        'startMinutes': time_to_minutes(start),
        'endMinutes': time_to_minutes(end),
        'label': label,
        'color': color,
        'repeatDays': [],
        'is_gcal': False,
        'is_pending': True,
        'session_id': session_id
    }
    busy_slots.append(slot)

    return f"Added: {label} on {date} {start}-{end}"


def get_busy_slots_for_date(date: str) -> str:
    """Get all busy slots for a specific date."""
    from main import slots_for_date, sync_gcal_events

    sync_gcal_events()
    slots = slots_for_date(date)

    if not slots:
        return f"No busy slots on {date}."

    lines = []
    for s in slots:
        status = "✓" if not s.get('is_pending') else "?"
        lines.append(f"- [{status}] {s['start']}-{s['end']} {s['label']}")

    return "Busy slots:\n" + "\n".join(lines)


def break_task_into_steps(task_description: str, total_hours: float) -> str:
    """Break a task into steps using NVIDIA NIM."""
    from agno.models.nvidia import Nvidia
    
    nvidia_model = Nvidia(id="nvidia/nemotron-3-super-120b-a12b")
    client = nvidia_model.get_client()
    
    system_instruction = f"""You are an AI task scheduler.
    Break the task into steps. Each step MUST have:
    - title: string (clear step name)
    - duration_hours: number (can be 0)
    - duration_minutes: number (multiple of 5: 0,5,10,15,20,30,45)
    
    Total requested: {total_hours} hours.
    
    Return ONLY a JSON array. No markdown, no backticks.
    Example: [{{"title":"Step 1","duration_hours":1,"duration_minutes":30}}]
    """
    
    response = client.chat.completions.create(
        model="nvidia/nemotron-3-super-120b-a12b",
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": task_description}
        ]
    )
    text = response.choices[0].message.content.strip()
    
    text = re.sub(r'^```json', '', text)
    text = re.sub(r'^```', '', text)
    text = re.sub(r'```$', '', text)
    text = text.strip()
    
    try:
        steps = json.loads(text)
        lines = [f"- {s['title']}: {s['duration_hours']}h {s['duration_minutes']}m" for s in steps]
        return "Task steps:\n" + "\n".join(lines)
    except json.JSONDecodeError:
        return f"Failed to parse steps. Raw: {text[:200]}"


def sync_calendar() -> str:
    """Sync events from Google Calendar."""
    from main import sync_gcal_events

    try:
        sync_gcal_events(force=True)
        return "Calendar synced successfully."
    except Exception as e:
        return f"Sync failed: {str(e)}"


def get_schedule_summary(date: str) -> str:
    """Get a summary of the schedule for a date."""
    from main import slots_for_date, sync_gcal_events, compute_free_blocks

    sync_gcal_events()
    busy = slots_for_date(date)

    total_busy_hours = sum((s['endMinutes'] - s['startMinutes']) / 60 for s in busy)
    total_free_hours = 24.0 - total_busy_hours - 6.0

    lines = [
        f"Date: {date}",
        f"Busy: {len(busy)} blocks ({total_busy_hours:.1f}h)",
        f"Free: ~{total_free_hours:.1f}h"
    ]

    return "\n".join(lines)


def save_user_preference(preference: str) -> str:
    """Auto-detect category and save preference."""
    pref_lower = preference.lower()

    if any(k in pref_lower for k in ['time', 'hour', 'morning', 'afternoon', 'evening', 'slot']):
        category = 'time'
    elif any(k in pref_lower for k in ['duration', 'long', 'short', 'break']):
        category = 'duration'
    elif any(k in pref_lower for k in ['style', 'format', 'color', 'theme']):
        category = 'style'
    else:
        category = 'general'

    return store_preference(category, preference)


def get_all_preferences() -> str:
    """Get all stored preferences by category."""
    return retrieve_preferences(None)


def get_day_overview(date: str) -> str:
    """Get a detailed overview of a day's schedule."""
    return get_schedule_summary(date) + "\n\n" + get_busy_slots_for_date(date)


def delete_block_by_id(slot_id: int) -> str:
    """Delete a scheduled block by its ID."""
    from main import busy_slots

    original_count = len(busy_slots)
    busy_slots[:] = [s for s in busy_slots if s.get('id') != slot_id]

    if len(busy_slots) == original_count:
        return f"Slot {slot_id} not found."

    return f"Deleted slot {slot_id}."


memory_agent = Agent(
    name="Memory Agent",
    role="Stores and retrieves user preferences",
    model=Nvidia(id="nvidia/nemotron-3-super-120b-a12b"),
    db=agent_sessions_db,
    tools=[store_preference, retrieve_preferences, delete_preference],
    instructions=[
        "You are a memory assistant that helps users store and retrieve their preferences.",
        "Always respond with clear confirmation when storing preferences.",
        "When retrieving, organize by category if multiple exist.",
        "If no preferences exist, say so clearly.",
        "Never fabricate preferences - only return what is actually stored."
    ]
)

scheduler_agent = Agent(
    name="Scheduler Agent",
    role="Finds free time and manages schedule blocks",
    model=Nvidia(id="nvidia/nemotron-3-super-120b-a12b"),
    db=scheduler_db,
    tools=[find_free_time, add_busy_block, get_busy_slots_for_date, break_task_into_steps, sync_calendar, get_schedule_summary],
    instructions=[
        "You are a scheduling assistant that helps users manage their time.",
        "NEVER schedule between 22:00-06:00 unless user explicitly allows.",
        "When adding blocks, always mark them as pending (is_pending=True).",
        "Use break_task_into_steps for any task breakdown request.",
        "Always sync calendar before showing free slots.",
        "Report findings in a clear, readable format.",
        "If no free time available, suggest alternative dates."
    ]
)

planner_agent = Agent(
    name="Planner Agent",
    role="Orchestrates scheduling tasks",
    model=Nvidia(id="nvidia/nemotron-3-super-120b-a12b"),
    db=memory_db,
    tools=[save_user_preference, get_all_preferences, get_day_overview, delete_block_by_id, find_free_time, add_busy_block, get_busy_slots_for_date, break_task_into_steps, sync_calendar, get_schedule_summary, store_preference, retrieve_preferences, delete_preference],
    add_history_to_context=True,
    num_history_messages=10,
    markdown=True,
    instructions=[
        "You are the main planning orchestrator.",
        "Use the Scheduler Agent for time finding and block management.",
        "Use the Memory Agent for preference storage/retrieval.",
        "Always check user preferences before suggesting times.",
        "Break complex tasks into steps using the Scheduler.",
        "NEVER schedule between 22:00-06:00 (sleep hours) unless user explicitly allows.",
        "When a task is given, first break it into steps, then schedule each step.",
        "After scheduling, provide a summary with Accept/Reject options.",
        "Never commit to calendar without user confirmation (pending status).",
        "Store user preferences for future sessions.",
        "Provide clear Accept/Reject buttons in responses for frontend.",
        "Use markdown formatting for clear response display.",
        "Include session_id in all scheduled blocks for tracking.",
        "Respond in a friendly, helpful tone.",
        "If unclear, ask the user for clarification before proceeding."
    ]
)


def run_planner(prompt: str, session_id: str, user_id: str = "default_user") -> dict:
    try:
        response = planner_agent.run(
            input=prompt,
            session_id=session_id,
            user_id=user_id
        )

        response_text = ""
        if hasattr(response, 'content'):
            response_text = response.content
        elif hasattr(response, 'messages') and response.messages:
            response_text = response.messages[-1].content if response.messages else str(response)
        else:
            response_text = str(response)

        return {
            "response": response_text,
            "session_id": session_id
        }
    except Exception as e:
        return {
            "response": f"Error: {str(e)}",
            "session_id": session_id,
            "error": True
        }


def get_pending_blocks(session_id: str) -> list:
    from main import busy_slots

    pending = [
        s for s in busy_slots
        if s.get('is_pending', False) and s.get('session_id') == session_id
    ]
    return pending