from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.schemas.auth import AuthRequest, TimezoneRequest, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/signup", response_model=UserResponse)
def signup(data: AuthRequest, response: Response, session: Session = Depends(get_session)):
    try:
        user = auth_service.create_user(session, data.email, data.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_service.set_auth_cookie(response, auth_service.create_access_token(user.id))
    return UserResponse(
        id=user.id, email=user.email, timezone=user.timezone, timezone_confirmed=user.timezone_confirmed
    )


@router.post("/auth/login", response_model=UserResponse)
def login(data: AuthRequest, response: Response, session: Session = Depends(get_session)):
    user = auth_service.authenticate_user(session, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    auth_service.set_auth_cookie(response, auth_service.create_access_token(user.id))
    return UserResponse(
        id=user.id, email=user.email, timezone=user.timezone, timezone_confirmed=user.timezone_confirmed
    )


@router.post("/auth/logout")
def logout(response: Response):
    auth_service.clear_auth_cookie(response)
    return {"success": True}


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(auth_service.get_current_user)):
    return UserResponse(
        id=user.id, email=user.email, timezone=user.timezone, timezone_confirmed=user.timezone_confirmed
    )


@router.put("/me/timezone", response_model=UserResponse)
def timezone(
    data: TimezoneRequest,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    from app.db.transactions import changed, lock_calendar
    from app.services.scheduler_service import user_blocks

    owner = lock_calendar(session, user.id)
    if owner.timezone != data.timezone and user_blocks(session, user.id):
        raise HTTPException(
            409,
            "Timezone changes with existing events require a separate calendar conversion. Keep the current timezone or start an empty calendar.",
        )
    owner.timezone = data.timezone
    owner.timezone_confirmed = True
    changed(session, owner)
    session.add(owner)
    session.commit()
    return UserResponse(id=owner.id, email=owner.email, timezone=owner.timezone, timezone_confirmed=True)
