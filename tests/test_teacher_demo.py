"""Teacher demo suite: the requests the presenter types, run against the RUNNING local app.

Start the app first (`python scripts/dev.py up --lan`), then seed a fresh week (`python scripts/dev.py seed`).

    python -m pytest -m teacher_demo -q                  fast checks, no AI (about 10 seconds)
    DEMO_AI=1 python -m pytest -m teacher_demo -q        also the assistant requests (about 5 minutes)

The AI requests use Groq's free quota and pause 35 seconds before each one. They add events to the demo
calendar on purpose, so the week looks full for the presentation. Re-seed before running them again.
"""

import os
import time
import uuid
from datetime import date, timedelta

import httpx
import pytest

from app.demo_seed import DEMO_EMAIL, DEMO_PASSWORD

BASE = os.getenv("DEMO_BASE_URL", "http://127.0.0.1:8000")
AI = os.getenv("DEMO_AI") == "1"
PAUSE_SECONDS = 35

pytestmark = pytest.mark.teacher_demo

# (what the presenter types, a word the new event's title should contain)
TEACHER_REQUESTS = [
    ("Study group tomorrow at 6pm for 1 hour", "Study"),
    ("Add a review of my project tomorrow at 9 am", "review"),
    ("Schedule a 2 hour Python practice on Sunday at 10 am", "Python"),
    ("Add a dentist appointment on Friday at 3 pm for 1 hour", "dentist"),
    ("Study session on Wednesday at 8 pm for 90 minutes", "Study"),
]


def _server_is_up() -> bool:
    try:
        return httpx.get(f"{BASE}/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def api():
    if not _server_is_up():
        pytest.skip(f"The app is not running at {BASE}. Start it with: python scripts/dev.py up --lan")
    with httpx.Client(base_url=BASE, timeout=90) as client:
        response = client.post("/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        assert response.status_code == 200, response.text
        yield client


def _free_sunday(weeks_ahead: int) -> str:
    """A Sunday with no seeded events, at least five weeks away."""
    today = date.today()
    return (today + timedelta(days=(6 - today.weekday()) + 35 + 7 * weeks_ahead)).isoformat()


def _events_in_next_fortnight(client) -> int:
    today = date.today()
    days = client.get(
        "/api/slots/range",
        params={"start": today.isoformat(), "end": (today + timedelta(days=13)).isoformat()},
    ).json()
    return sum(len(events) for events in days.values())


def _wait(client, run: dict, limit: int = 180) -> dict:
    started = time.time()
    while run["status"] in ("queued", "running") and time.time() - started < limit:
        time.sleep(0.5)
        run = client.get(f"/api/agent/runs/{run['run_id']}").json()
    return run


def _ask(client, prompt: str) -> dict:
    body = {"prompt": prompt, "request_id": uuid.uuid4().hex}
    return _wait(client, client.post("/api/agent/chat", json=body).json())


# ── fast checks: no AI ───────────────────────────────────────────────────────────────────────────


def test_demo_week_is_full(api):
    start = date.today() - timedelta(days=date.today().weekday())
    days = api.get(
        "/api/slots/range",
        params={"start": start.isoformat(), "end": (start + timedelta(days=6)).isoformat()},
    ).json()
    labels = {event["label"] for events in days.values() for event in events}
    assert {"Calculus lecture", "Physics lab", "Gym", "Part-time job"} <= labels, sorted(labels)


def test_hand_added_study_block_saves_and_overlaps_are_refused(api):
    day = _free_sunday(0)
    body = {"date": day, "start": "10:00", "end": "11:00", "label": "Teacher demo study", "color": "#0277bd"}
    created = api.post("/api/slots", json=body)
    assert created.status_code == 201, created.text
    try:
        clash = api.post("/api/slots", json={**body, "start": "10:30", "end": "11:30", "label": "Clash"})
        assert clash.status_code == 400 and "overlap" in clash.json()["error"].lower(), clash.text
    finally:
        api.delete(f"/api/slots/{created.json()['id']}")


def test_free_time_is_found_for_a_two_hour_session(api):
    result = api.get("/api/free", params={"hours": 2}).json()
    assert result["fulfilled"] and result["allocated"], result


# ── assistant requests: Groq free quota, opt in with DEMO_AI=1 ──────────────────────────────────


@pytest.mark.skipif(not AI, reason="set DEMO_AI=1 to run the assistant requests")
@pytest.mark.parametrize("prompt,word", TEACHER_REQUESTS, ids=[p for p, _ in TEACHER_REQUESTS])
def test_request_becomes_a_draft_and_approving_adds_it(api, prompt, word):
    time.sleep(PAUSE_SECONDS)
    before = _events_in_next_fortnight(api)
    run = _ask(api, prompt)
    assert run["status"] == "awaiting_approval", (run["status"], run.get("error"), run.get("pending"))
    draft = run["draft"]
    body = {"session_id": run["session_id"], "draft_id": draft["id"], "revision": draft["revision"]}
    saved = _wait(api, api.post("/api/agent/confirm", json=body).json())
    assert saved["status"] == "completed", saved
    assert _events_in_next_fortnight(api) == before + 1
    assert word.lower() in str(draft["preview"]).lower()


@pytest.mark.skipif(not AI, reason="set DEMO_AI=1 to run the assistant requests")
def test_vague_time_asks_am_or_pm_and_saves_nothing(api):
    time.sleep(PAUSE_SECONDS)
    before = _events_in_next_fortnight(api)
    run = _ask(api, f"schedule gym at 7 on {_free_sunday(1)}")
    assert run["status"] == "awaiting_input", (run["status"], run.get("error"))
    assert "AM or PM" in run["pending"]["question"], run["pending"]
    api.post(f"/api/agent/runs/{run['run_id']}/cancel")
    assert _events_in_next_fortnight(api) == before


@pytest.mark.skipif(not AI, reason="set DEMO_AI=1 to run the assistant requests")
def test_rejecting_a_draft_saves_nothing(api):
    time.sleep(PAUSE_SECONDS)
    before = _events_in_next_fortnight(api)
    run = _ask(api, f"add a chemistry quiz on {_free_sunday(2)} at 3 pm for 1 hour")
    assert run["status"] == "awaiting_approval", (run["status"], run.get("error"))
    draft = run["draft"]
    body = {"session_id": run["session_id"], "draft_id": draft["id"], "revision": draft["revision"]}
    _wait(api, api.post("/api/agent/reject", json=body).json())
    assert _events_in_next_fortnight(api) == before
