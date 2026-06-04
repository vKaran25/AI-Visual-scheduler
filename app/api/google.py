from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.services import auth_service, calendar_service

router = APIRouter(prefix="/api/google", tags=["google"])
oauth_state_store = {}


@router.get("/status")
def google_status(user: User = Depends(auth_service.get_current_user)):
    return {"connected": calendar_service.get_gcal_credentials(user) is not None}


@router.post("/oauth/logout")
def google_logout(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    calendar_service.disconnect_google(session, user)
    return {"success": True}


@router.get("/oauth/login")
def google_login(user: User = Depends(auth_service.get_current_user)):
    auth_url, state, code_verifier = calendar_service.build_authorization_url()
    oauth_state_store[state] = {"code_verifier": code_verifier, "user_id": user.id}
    return RedirectResponse(auth_url)


@router.get("/oauth/callback")
def google_callback(request: Request, state: str | None = None, session: Session = Depends(get_session)):
    stored = oauth_state_store.pop(state, {}) if state else {}
    user = session.get(User, stored.get("user_id"))
    if not user:
        return HTMLResponse("<script>window.close();</script>")
    calendar_service.save_callback_credentials(user, str(request.url), state=state, code_verifier=stored.get("code_verifier"))
    calendar_service.sync_gcal_events(session, user, force=True)
    return HTMLResponse("<script>window.opener ? window.close() : window.location.href='/';</script>")

