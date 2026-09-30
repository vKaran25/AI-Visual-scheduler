import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from app.db.models import User
from app.db.session import get_session
from app.services import auth_service, calendar_service

router = APIRouter(prefix="/api/google", tags=["google"])
OAUTH_STATE_LIFETIME = timedelta(minutes=10)


@router.get("/status")
def google_status(user: User = Depends(auth_service.get_current_user)):
    return {"connected": calendar_service.get_gcal_credentials(user) is not None}


@router.post("/oauth/logout")
def google_logout(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    calendar_service.disconnect_google(session, user)
    return {"success": True}


@router.get("/oauth/login")
def google_login(request: Request, user: User = Depends(auth_service.get_current_user)):
    # Signed, short-lived state binds the callback to the initiating browser's auth cookie.
    state = jwt.encode(
        {"sub": str(user.id), "cookie": hashlib.sha256(request.cookies[auth_service.AUTH_COOKIE].encode()).hexdigest(),
         "exp": datetime.now(timezone.utc) + OAUTH_STATE_LIFETIME, "type": "google_oauth", "jti": secrets.token_urlsafe(16)},
        JWT_SECRET_KEY, algorithm=JWT_ALGORITHM,
    )
    auth_url, _, _ = calendar_service.build_authorization_url(state=state)
    return RedirectResponse(auth_url)


@router.get("/oauth/callback")
def google_callback(
    request: Request, state: str | None = None, session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    if not state or request.query_params.get("error") or not request.query_params.get("code"):
        raise HTTPException(status_code=400, detail="Google authorization was cancelled or invalid")
    try:
        payload = jwt.decode(state, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired Google authorization") from exc
    cookie_hash = hashlib.sha256(request.cookies[auth_service.AUTH_COOKIE].encode()).hexdigest()
    if (payload.get("type") != "google_oauth" or payload.get("sub") != str(user.id)
            or not hmac.compare_digest(str(payload.get("cookie", "")), cookie_hash)):
        raise HTTPException(status_code=400, detail="Google authorization does not match this session")
    # Use the configured redirect URI rather than a proxy-supplied Host or scheme.
    authorization_response = f"{calendar_service.get_google_redirect_uri()}?{urlencode(request.query_params.multi_items())}"
    try:
        calendar_service.save_callback_credentials(user, authorization_response, state=state)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Google authorization failed") from exc
    calendar_service.sync_gcal_events(session, user, force=True)
    return HTMLResponse("<script>window.opener ? window.close() : window.location.href='/';</script>")

