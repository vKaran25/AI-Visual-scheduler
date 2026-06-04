from datetime import datetime, timedelta

from sqlmodel import Session

from app.db.models import User
from app.services import preset_service, scheduler_service


def _date_range(start_date: str, end_date: str | None = None) -> list[str]:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date() if end_date else start
    if end < start:
        raise ValueError("end_date must be after start_date")
    days = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def get_schedule(session: Session, user: User, start_date: str, end_date: str | None = None) -> dict:
    return {
        date: scheduler_service.slots_for_date(session, user, date)
        for date in _date_range(start_date, end_date)
    }


def find_free_time(session: Session, user: User, start_dt: str, hours: float) -> dict:
    return scheduler_service.compute_free_blocks(session, user, start_dt, hours)


def create_pending_block(session: Session, user: User, session_id: str, block_data: dict) -> dict:
    block = scheduler_service.create_block(session, user, block_data, is_pending=True, session_id=session_id)
    return scheduler_service.block_to_dict(block)


def apply_preset(session: Session, user: User, preset_id: str, clear_existing: bool = False) -> dict:
    return preset_service.apply_preset(session, user, preset_id, clear_existing)


def save_custom_preset(session: Session, user: User, name: str, description: str = "") -> dict:
    preset = preset_service.create_custom_preset(session, user, name, description)
    return {"id": preset.id, "name": preset.name, "description": preset.description}


def detect_conflicts(session: Session, user: User, start_date: str, end_date: str | None = None) -> list[dict]:
    conflicts = []
    for date in _date_range(start_date, end_date):
        conflicts.extend(scheduler_service.detect_conflicts(session, user, date))
    return conflicts


def commit_pending_plan(session: Session, user: User, session_id: str) -> list[dict]:
    blocks = scheduler_service.accept_pending_slots(session, user, session_id)
    return [scheduler_service.block_to_dict(block) for block in blocks]


def reject_pending_plan(session: Session, user: User, session_id: str) -> None:
    scheduler_service.reject_pending_slots(session, user, session_id)
