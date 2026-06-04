from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.schemas.presets import ApplyPresetRequest, CustomPresetRequest
from app.services import auth_service, preset_service

router = APIRouter(prefix="/api", tags=["presets"])


@router.get("/presets")
def list_presets(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return preset_service.list_presets(session, user)


@router.post("/presets/{preset_id}/apply")
def apply_preset(
    preset_id: str,
    data: ApplyPresetRequest = Body(default_factory=ApplyPresetRequest),
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    try:
        return preset_service.apply_preset(session, user, preset_id, data.clear_existing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/custom-presets")
def create_custom_preset(
    data: CustomPresetRequest,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    preset = preset_service.create_custom_preset(session, user, data.name, data.description, data.blocks)
    return {"id": preset.id, "name": preset.name, "description": preset.description}


@router.put("/custom-presets/{preset_id}")
def update_custom_preset(
    preset_id: int,
    data: CustomPresetRequest,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    preset = preset_service.update_custom_preset(session, user, preset_id, data.name, data.description, data.blocks)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"id": preset.id, "name": preset.name, "description": preset.description}


@router.delete("/custom-presets/{preset_id}")
def delete_custom_preset(
    preset_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    preset_service.delete_custom_preset(session, user, preset_id)
    return {"success": True}
