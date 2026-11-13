"""Critical demo flows: create, conflict handling, MCP tools, and finished-run safety.

Approve and reject are covered against the real graph in test_agent_graph.py
(test_combined_graph_repairs_then_waits_for_approval, test_duplicate_requests_rejection_and_ownership).
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.contracts import EventData
from app.services import calendar_tools

ROOT = Path(__file__).resolve().parents[1]
DAY = "2030-01-07"  # a Monday


def test_manual_create_is_listed_and_overlap_is_rejected(client):
    body = {"date": DAY, "start": "09:00", "end": "10:00", "label": "Calculus", "color": "#0277bd"}
    created = client.post("/api/slots", json=body)
    assert created.status_code == 201, created.text
    listed = client.get("/api/slots/range", params={"start": DAY, "end": DAY}).json()
    assert [e["label"] for e in listed[DAY]] == ["Calculus"]
    clash = client.post("/api/slots", json={**body, "start": "09:30", "end": "10:30", "label": "Clash"})
    assert clash.status_code == 400
    assert "overlap" in clash.json()["error"].lower()


def test_event_color_is_validated_before_any_preview_is_built():
    with pytest.raises(ValidationError):
        EventData(date=DAY, start="09:00", end="10:00", color='red;" onmouseover="alert(1)')
    assert EventData(date=DAY, start="09:00", end="10:00", color="#397969").color == "#397969"


def test_cancel_does_not_rewrite_a_finished_run(db, user):
    from app.db.models import AgentRun, AgentSession
    from app.services import run_service

    conversation = AgentSession(user_id=user.id, prompt="done")
    db.add(conversation)
    db.flush()
    run = AgentRun(
        user_id=user.id,
        session_id=conversation.id,
        request_id="finished-run",
        graph_version="calendar-v1",
        input={},
        status="completed",
        result={"response": "Saved"},
    )
    db.add(run)
    db.commit()
    after = run_service.cancel(db, user, run.id)
    assert after.status == "completed" and after.result == {"response": "Saved"}


@pytest.mark.parametrize(
    "text,expected",
    [("16:30", "16:30"), ("4pm", "16:00"), ("4:30 PM", "16:30"), ("12am", "00:00"), ("12 pm", "12:00")],
)
def test_clock_parsing_accepts_student_friendly_times(text, expected):
    assert calendar_tools.parse_clock(text) == expected


@pytest.mark.parametrize("text", ["25:00", "4:75pm", "banana", "13pm"])
def test_clock_parsing_rejects_nonsense(text):
    with pytest.raises(ValueError):
        calendar_tools.parse_clock(text)


def test_propose_saves_nothing_and_create_saves_once(db, user):
    proposal = calendar_tools.propose_event(db, user, "Study group", DAY, "4pm", "5:30pm")
    assert proposal["valid"] and not proposal["saved"] and proposal["minutes"] == 90
    assert calendar_tools.list_events(db, user, DAY, DAY)["days"][DAY] == []

    saved = calendar_tools.create_event(db, user, "Study group", DAY, "16:00", "17:30")
    assert saved["saved"]
    events = calendar_tools.list_events(db, user, DAY, DAY)["days"][DAY]
    assert [(e["title"], e["start"], e["end"], e["status"]) for e in events] == [
        ("Study group", "16:00", "17:30", "confirmed")
    ]


def test_conflicting_proposal_explains_the_problem_and_offers_alternatives(db, user):
    calendar_tools.create_event(db, user, "Lecture", DAY, "09:00", "10:30")
    proposal = calendar_tools.propose_event(db, user, "Study", DAY, "10:00", "11:00")
    assert not proposal["valid"] and "overlap" in proposal["problem"].lower()
    assert proposal["alternatives"] and all(
        slot["date"] == DAY and slot["start"] >= "08:00" for slot in proposal["alternatives"]
    )
    with pytest.raises(ValueError):
        calendar_tools.create_event(db, user, "Study", DAY, "10:00", "11:00")


def test_listing_rejects_oversized_or_malformed_ranges(db, user):
    with pytest.raises(ValueError):
        calendar_tools.list_events(db, user, DAY, "2030-06-01")
    with pytest.raises(ValueError):
        calendar_tools.list_events(db, user, "next week", DAY)


def test_mcp_server_speaks_the_protocol_over_stdio(db, user):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "MCP_USER_EMAIL": user.email, "PYTHONPATH": str(ROOT)}

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "app.mcp_server"], env=env, cwd=str(ROOT)
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                proposed = await session.call_tool(
                    "propose_event", {"title": "MCP study", "date": DAY, "start": "14:00", "end": "15:00"}
                )
                created = await session.call_tool(
                    "create_event", {"title": "MCP study", "date": DAY, "start": "14:00", "end": "15:00"}
                )
                listed = await session.call_tool("list_events", {"start_date": DAY, "end_date": DAY})
                return names, proposed, created, listed

    names, proposed, created, listed = asyncio.run(scenario())
    assert names == {"list_events", "find_free_time", "propose_event", "create_event"}
    assert not proposed.is_error and '"valid": true' in proposed.content[0].text
    assert not created.is_error and '"saved": true' in created.content[0].text
    assert "MCP study" in listed.content[0].text
