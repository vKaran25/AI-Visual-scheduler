"""Demo readiness check against the RUNNING local app.  Usage:

    python scripts/dev.py check            fast checks, no AI (about 30 seconds)
    python scripts/dev.py check --ai       also exercises the assistant and voice agent (about 4 minutes)

Run `python scripts/dev.py up` in another terminal first. Uses the demo account from app/demo_seed.py and
removes anything it creates. The --ai checks pause between requests to respect Groq's free token limit.
"""

import argparse
import asyncio
import os
import sys
import time
import uuid
from datetime import date, timedelta

import httpx

from app.demo_seed import DEMO_EMAIL, DEMO_PASSWORD

BASE = os.getenv("DEMO_BASE_URL", "http://127.0.0.1:8000")
results: list[tuple[str, bool, str]] = []
client = httpx.Client(base_url=BASE, timeout=90)


def check(name):
    def wrap(fn):
        def run(*args, **kwargs):
            started = time.time()
            try:
                detail = fn(*args, **kwargs) or ""
                results.append((name, True, f"{detail} ({time.time() - started:.1f}s)".strip()))
            except Exception as error:  # noqa: BLE001 - report every failure, keep going
                results.append((name, False, f"{type(error).__name__}: {str(error)[:200]}"))
            status = "PASS" if results[-1][1] else "FAIL"
            print(f"  [{status}] {name}: {results[-1][2]}", flush=True)

        return run

    return wrap


def wait(run, limit=180):
    started = time.time()
    while run["status"] in ("queued", "running") and time.time() - started < limit:
        time.sleep(0.5)
        run = client.get(f"/api/agent/runs/{run['run_id']}").json()
    return run


def free_day(week=0):
    """A Sunday at least five weeks away: the demo week has no weekly events on Sundays."""
    today = date.today()
    return (today + timedelta(days=(6 - today.weekday()) + 35 + 7 * week)).isoformat()


# ── fast checks (no AI) ─────────────────────────────────────────────────────────────────────────────


@check("App is healthy")
def app_health():
    assert client.get("/health").json() == {"status": "ok"}


@check("Landing and app pages load")
def pages():
    assert client.get("/home").status_code == 200 and client.get("/").status_code == 200
    assert "tz-dialog" in client.get("/").text


@check("Sign in as the demo student")
def sign_in():
    response = client.post("/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["timezone_confirmed"]
    return response.json()["timezone"]


@check("Demo week is on the calendar")
def seeded_week():
    start = date.today() - timedelta(days=date.today().weekday())
    days = client.get(
        "/api/slots/range",
        params={"start": start.isoformat(), "end": (start + timedelta(days=6)).isoformat()},
    ).json()
    titles = {event["label"] for events in days.values() for event in events}
    assert {"Calculus lecture", "Lunch", "Gym"} <= titles, sorted(titles)
    return f"{sum(len(v) for v in days.values())} events this week"


@check("Add an event by hand, overlap is refused, delete works")
def manual_event():
    day = free_day()
    body = {"date": day, "start": "10:00", "end": "11:00", "label": "Demo check", "color": "#0277bd"}
    created = client.post("/api/slots", json=body)
    assert created.status_code == 201, created.text
    clash = client.post("/api/slots", json={**body, "start": "10:30", "end": "11:30"})
    assert clash.status_code == 400 and "overlap" in clash.json()["error"].lower(), clash.text
    assert client.delete(f"/api/slots/{created.json()['id']}").status_code == 200
    return clash.json()["error"][:70]


@check("Unsafe colours are rejected")
def bad_colour():
    body = {
        "date": free_day(1),
        "start": "10:00",
        "end": "11:00",
        "label": "x",
        "color": 'red;" onmouseover="x',
    }
    assert client.post("/api/slots", json=body).status_code == 400


@check("Find free time")
def free_time():
    result = client.get("/api/free", params={"hours": 2}).json()
    assert result["fulfilled"] and result["allocated"]
    return f"first slot {result['allocated'][0]['date']} {result['allocated'][0]['start']}"


@check("Voice endpoint rejects empty speech")
def voice_validation():
    assert (
        client.post("/api/voice/turn", json={"transcript": "", "request_id": uuid.uuid4().hex}).status_code
        == 422
    )


@check("MCP server lists its tools and checks an event (stdio)")
def mcp_tools():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "app.mcp_server"], env=dict(os.environ)
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = sorted(tool.name for tool in (await session.list_tools()).tools)
                proposal = await session.call_tool(
                    "propose_event",
                    {"title": "MCP check", "date": free_day(2), "start": "16:00", "end": "17:00"},
                )
                return names, proposal.content[0].text

    names, text = asyncio.run(scenario())
    assert names == ["create_event", "find_free_time", "list_events", "propose_event"], names
    assert '"valid": true' in text and '"saved": false' in text, text
    return "4 tools, proposal saved nothing"


# ── AI checks (Groq free plan: pause between requests) ─────────────────────────────────────────────


def pause(seconds=35):
    print(f"        ...waiting {seconds}s for the free token limit", flush=True)
    time.sleep(seconds)


def decide(run, accept):
    draft = run["draft"]
    path = "confirm" if accept else "reject"
    body = {"session_id": run["session_id"], "draft_id": draft["id"], "revision": draft["revision"]}
    return wait(client.post(f"/api/agent/{path}", json=body).json())


def ask(prompt):
    return wait(
        client.post("/api/agent/chat", json={"prompt": prompt, "request_id": uuid.uuid4().hex}).json()
    )


@check("AI: 'schedule 9 am review of project' goes straight to a draft")
def ai_simple_event():
    run = ask("schedule 9 am review of project")
    assert run["status"] == "awaiting_approval", (run["status"], run.get("error"))
    event = run["draft"]["preview"]["scheduled"][0]
    assert event["start"] == "09:00" and event["end"] == "10:00", event
    assert any("Length assumed" in note for note in run["draft"]["preview"].get("notes", []))
    decide(run, accept=False)
    return f"{event['label']} 09:00-10:00, assumption shown"


@check("AI: approve saves the event, reject saves nothing")
def ai_approve_reject():
    day = free_day(3)
    run = ask(f"add a study group on {day} at 6 pm for 1 hour called Algorithms review")
    assert run["status"] == "awaiting_approval", (run["status"], run.get("error"), run.get("pending"))
    saved = decide(run, accept=True)
    assert saved["status"] == "completed", saved
    events = client.get("/api/slots", params={"date": day}).json()
    match = [e for e in events if "lgorithm" in e["label"]]
    assert match, [e["label"] for e in events]
    client.delete(f"/api/slots/{match[0]['id']}")
    pause()
    run = ask(f"add a chemistry quiz on {day} at 3 pm for 1 hour")
    assert run["status"] == "awaiting_approval", (run["status"], run.get("error"))
    decide(run, accept=False)
    assert not [e for e in client.get("/api/slots", params={"date": day}).json() if "uiz" in e["label"]]
    return "approved event appeared, rejected one did not"


@check("AI: asks only when AM/PM is unclear")
def ai_clarify():
    run = ask("schedule gym at 7 on " + free_day(4))
    assert run["status"] == "awaiting_input", (run["status"], run.get("error"))
    question = run["pending"]["question"]
    assert "AM or PM" in question, question
    client.post(f"/api/agent/runs/{run['run_id']}/cancel")
    return question[:60]


@check("Voice agent: reads the schedule, adds an event, saves it on 'yes'")
def ai_voice():
    session = None

    def say(text):
        nonlocal session
        reply = client.post(
            "/api/voice/turn",
            json={"transcript": text, "session_id": session, "request_id": uuid.uuid4().hex},
        ).json()
        session = reply.get("session_id") or session
        return reply

    first = say("what is on my calendar today?")
    assert first["action"] == "read_schedule" and first["say"], first
    pause(20)
    day = free_day(5)
    second = say(f"add a project review on {day} at 11 am")
    assert second["action"] == "delegate" and second["run"], second
    run = wait(second["run"])
    assert run["status"] == "awaiting_approval", (run["status"], run.get("error"))
    pause(20)
    third = say("yes, save it")
    assert third["action"] == "approve", third
    done = wait(third["run"])
    assert done["status"] == "completed", done
    for event in client.get("/api/slots", params={"date": day}).json():
        if "eview" in event["label"]:
            client.delete(f"/api/slots/{event['id']}")
    return "read schedule, delegated, approved by voice"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ai", action="store_true", help="also run the assistant and voice agent checks")
    args = parser.parse_args()
    print(f"Demo check against {BASE}\n")
    try:
        client.get("/health")
    except httpx.HTTPError:
        sys.exit("The app is not running. Start it with: python scripts/dev.py up")
    print("Fast checks")
    for fn in (
        app_health,
        pages,
        sign_in,
        seeded_week,
        manual_event,
        bad_colour,
        free_time,
        voice_validation,
        mcp_tools,
    ):
        fn()
    if args.ai:
        print("\nAI checks (a few minutes; paced for Groq's free plan)")
        for index, fn in enumerate((ai_simple_event, ai_approve_reject, ai_clarify, ai_voice)):
            if index:
                pause()
            fn()
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    if failed:
        print("FAILED:", "; ".join(failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
