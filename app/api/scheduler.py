from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.schemas.scheduler import BlockRequest, DefaultBlocksRequest
from app.services import auth_service, calendar_service, scheduler_service
from app.services.time_utils import parse_positive_float

router = APIRouter(prefix="/api", tags=["scheduler"])


@router.get("/settings/default-blocks")
def get_default_blocks_setting(user: User = Depends(auth_service.get_current_user)):
    return {"enabled": user.default_blocks_enabled}


@router.put("/settings/default-blocks")
def update_default_blocks_setting(
    data: DefaultBlocksRequest,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    return scheduler_service.set_default_blocks_enabled(session, user, data.enabled)


@router.get("/slots")
def get_slots(
    date: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    calendar_service.sync_gcal_events(session, user)
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    try:
        return scheduler_service.slots_for_date(session, user, date_str)
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
    scheduler_service.delete_block(session, user, slot_id)
    return {"success": True}


@router.get("/free")
def get_free(
    start_dt: str | None = None,
    hours: str | float = 1,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    calendar_service.sync_gcal_events(session, user)
    start = start_dt or datetime.now().isoformat(timespec="minutes")
    parsed_hours = parse_positive_float(hours, 1.0)
    try:
        return scheduler_service.compute_free_blocks(session, user, start, parsed_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid start_dt format") from exc

