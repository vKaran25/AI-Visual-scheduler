from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.domain.time_utils import snap_to_30_min, validate_calendar_date
from app.integrations.google_sync import queue_import
from app.schemas.scheduler import BlockRequest
from app.services import auth_service, draft_service, scheduler_service

router = APIRouter(prefix="/api", tags=["scheduler"])


@router.get("/slots/range")
def get_slots_range(
    start: str,
    end: str,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    """Expand recurring blocks for a calendar view with one database read."""
    try:
        first = datetime.strptime(validate_calendar_date(start), "%Y-%m-%d").date()
        last = datetime.strptime(validate_calendar_date(end), "%Y-%m-%d").date()
        if not 0 <= (last - first).days <= 41:
            raise ValueError("Choose a range of 1 to 42 days")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    queue_import(session, user, [first.isoformat(), last.isoformat()])
    blocks = scheduler_service.user_blocks(session, user.id)
    return {
        (day := first + timedelta(days=offset)).isoformat(): [
            scheduler_service.block_to_dict(block, display_date=day.isoformat())
            for block in blocks
            if scheduler_service.slot_applies_to_date(block, day.isoformat())
        ]
        + draft_service.overlays(session, user, day.isoformat())
        for offset in range((last - first).days + 1)
    }


@router.get("/slots")
def get_slots(
    date: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    try:
        validate_calendar_date(date_str)
        queue_import(session, user, [date_str])
        return scheduler_service.slots_for_date(session, user, date_str) + draft_service.overlays(
            session, user, date_str
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date format") from exc


@router.post("/slots")
def add_slot(
    data: BlockRequest,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    try:
        block = scheduler_service.create_block(session, user, data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(scheduler_service.block_to_dict(block), status_code=201)


@router.put("/slots/{slot_id}")
def update_slot(
    slot_id: int,
    data: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    try:
        block = scheduler_service.update_block(session, user, slot_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not block:
        raise HTTPException(status_code=404, detail="Not found")
    return scheduler_service.block_to_dict(block)


@router.delete("/slots/{slot_id}")
def delete_slot(
    slot_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    try:
        deleted = scheduler_service.delete_block(session, user, slot_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Not found")
    return {"success": True}


@router.get("/free")
def get_free(
    start_dt: str | None = None,
    hours: str | float = 1,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    start = start_dt or snap_to_30_min(datetime.now()).isoformat(timespec="minutes")
    try:
        parsed_hours = float(hours)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "hours must be a positive finite number") from exc
    try:
        parsed_start = datetime.fromisoformat(start)
        queue_import(
            session,
            user,
            [parsed_start.date().isoformat(), (parsed_start.date() + timedelta(days=60)).isoformat()],
        )
        return scheduler_service.compute_free_blocks(session, user, start, parsed_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
