"""Load a realistic student week for demos.  Usage: python scripts/dev.py seed

Creates (or resets) a local demo account and fills the current week. Safe to run repeatedly:
it replaces that account's non-Google events each time. Demo account only; never use these
credentials on a shared or public instance.
"""

import argparse
from datetime import timedelta

from sqlmodel import Session

from app.db.models import utc_now
from app.db.session import engine, verify_schema
from app.domain.time import local_now
from app.services import auth_service, scheduler_service

DEMO_EMAIL = "student@example.com"
DEMO_PASSWORD = "predestination-demo"
DEMO_TIMEZONE = "Asia/Kolkata"

GREEN, BLUE, PURPLE, ORANGE, PINK, GREY = "#2e7d32", "#0277bd", "#7c6aff", "#e65100", "#d81b60", "#546e7a"

WEEKLY = [
    ("Calculus lecture", [0, 2, 4], "09:00", "10:30", BLUE),
    ("Physics lecture", [1, 3], "10:00", "11:30", BLUE),
    ("Physics lab", [2], "14:00", "17:00", PURPLE),
    ("Lunch", [0, 1, 2, 3, 4], "13:00", "13:45", GREY),
    ("Gym", [0, 3], "18:00", "19:00", GREEN),
    ("Club meeting", [4], "16:00", "17:00", ORANGE),
    ("Part-time job", [5], "11:00", "15:00", PINK),
]
# (title, days from today, start, end, color)
ONE_OFF = [
    ("Group project call", 1, "20:00", "21:00", ORANGE),
    ("Chemistry quiz", 3, "11:45", "12:45", PINK),
    ("Data Structures assignment due", 4, "22:00", "22:30", PINK),
]


def seed(email=DEMO_EMAIL, password=DEMO_PASSWORD, zone=DEMO_TIMEZONE) -> dict:
    with Session(engine, expire_on_commit=False) as db:
        user = auth_service.get_user_by_email(db, email) or auth_service.create_user(db, email, password)
        user.timezone, user.timezone_confirmed = zone, True
        db.add(user)
        db.commit()
        scheduler_service.delete_blocks_by_flags(db, user)
        today = local_now(zone).date()
        created, skipped = 0, []
        for title, days, start, end, color in WEEKLY:
            specs = [{"label": title, "start": start, "end": end, "color": color, "repeatDays": days}]
            for spec in specs:
                scheduler_service.create_block(db, user, spec)
                created += 1
        for title, offset, start, end, color in ONE_OFF:
            spec = {
                "label": title,
                "date": (today + timedelta(days=offset)).isoformat(),
                "start": start,
                "end": end,
                "color": color,
            }
            try:
                scheduler_service.create_block(db, user, spec)
                created += 1
            except ValueError as exc:  # a weekly event already owns this slot on that weekday
                skipped.append(f"{title}: {exc}")
        return {"email": email, "timezone": zone, "events": created, "skipped": skipped, "at": utc_now()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    parser.add_argument("--timezone", default=DEMO_TIMEZONE)
    args = parser.parse_args()
    verify_schema()
    result = seed(args.email, args.password, args.timezone)
    print(f"Demo account ready: {result['email']} ({result['timezone']}), {result['events']} events.")
    print("Password: see DEMO_PASSWORD in app/demo_seed.py")
    for line in result["skipped"]:
        print("Skipped:", line)


if __name__ == "__main__":
    main()
