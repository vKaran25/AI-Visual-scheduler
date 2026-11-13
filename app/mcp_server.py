"""MCP server: lets an AI client (Claude Desktop, Claude Code, ...) use the Predestination calendar.

Run over stdio:  python scripts/dev.py mcp      (or:  python -m app.mcp_server)

It acts as ONE configured account (environment variable MCP_USER_EMAIL) and talks to the same
database as the web app, so the web calendar shows anything created here. It is meant for local
use; do not expose it over a network transport without adding authentication.

Nothing may be written to stdout except protocol messages, so diagnostics go to stderr.
"""

import os
import sys
from contextlib import contextmanager

from mcp.server import MCPServer
from sqlmodel import Session

from app.db.session import engine
from app.services import auth_service, calendar_tools

mcp = MCPServer(
    "Predestination Calendar",
    instructions=(
        "Tools for a student's calendar. Times are 24-hour HH:MM in the calendar's own timezone. "
        "Use propose_event first and show the result to the user; only call create_event after the "
        "user agrees. create_event saves immediately."
    ),
)


@contextmanager
def _session():
    email = os.getenv("MCP_USER_EMAIL", "").strip()
    if not email:
        raise ValueError("MCP_USER_EMAIL is not set. Add it to .env, then restart the MCP server.")
    with Session(engine, expire_on_commit=False) as db:
        user = auth_service.get_user_by_email(db, email)
        if user is None:
            raise ValueError(f"No account for {email}. Sign up in the app or run: python scripts/dev.py seed")
        yield db, user


@mcp.tool()
def list_events(start_date: str, end_date: str) -> dict:
    """List calendar events from start_date to end_date (YYYY-MM-DD, at most 42 days).

    Includes weekly repeating events for each day and assistant proposals still awaiting approval,
    which are marked as not saved.
    """
    with _session() as (db, user):
        return calendar_tools.list_events(db, user, start_date, end_date)


@mcp.tool()
def find_free_time(hours: float, from_datetime: str | None = None) -> dict:
    """Find the earliest free time slots that add up to `hours`.

    from_datetime is an optional local ISO time such as 2026-11-16T09:00 (default: now).
    """
    with _session() as (db, user):
        return calendar_tools.find_free_time(db, user, hours, from_datetime)


@mcp.tool()
def propose_event(title: str, date: str, start: str, end: str, color: str | None = None) -> dict:
    """Check an event against the calendar WITHOUT saving it.

    date is YYYY-MM-DD; start and end are 24-hour times such as 16:30 (4pm style also works).
    Returns whether it fits, a readable summary, or the conflict plus alternative free slots.
    """
    with _session() as (db, user):
        return calendar_tools.propose_event(db, user, title, date, start, end, color)


@mcp.tool()
def create_event(title: str, date: str, start: str, end: str, color: str | None = None) -> dict:
    """Save an event to the calendar. Only call this after the user agreed to a proposal."""
    with _session() as (db, user):
        return calendar_tools.create_event(db, user, title, date, start, end, color)


if __name__ == "__main__":
    print("Predestination MCP server starting (stdio)", file=sys.stderr)
    mcp.run()
