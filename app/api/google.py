"""Google authorization and observable durable synchronization."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from app.db.models import GoogleConnection, SyncJob, User, utc_now
from app.db.session import get_session
from app.integrations import google
from app.integrations.google_sync import queue_import
from app.services import auth_service

router = APIRouter(prefix="/api/google", tags=["google"])


@router.get("/status")
def status(db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    connection = db.get(GoogleConnection, user.id)
    return {"connected": connection is not None, "sync_error": connection.sync_error if connection else None}


@router.post("/oauth/logout")
def logout(db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    google.disconnect_google(db, user)
    return {"success": True}


@router.get("/oauth/login")
def login(request: Request, user: User = Depends(auth_service.get_current_user)):
    state = jwt.encode(
        {
            "sub": str(user.id),
            "cookie": hashlib.sha256(request.cookies[auth_service.AUTH_COOKIE].encode()).hexdigest(),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "type": "google_oauth",
            "jti": secrets.token_urlsafe(16),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    url, _, _ = google.build_authorization_url(state)
    return RedirectResponse(url)


@router.get("/oauth/callback")
def callback(
    request: Request,
    state: str | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    if not state or request.query_params.get("error") or not request.query_params.get("code"):
        raise HTTPException(400, "Google authorization was cancelled or invalid")
    try:
        payload = jwt.decode(state, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(400, "Invalid or expired Google authorization") from exc
    cookie_hash = hashlib.sha256(request.cookies[auth_service.AUTH_COOKIE].encode()).hexdigest()
    if (
        payload.get("type") != "google_oauth"
        or payload.get("sub") != str(user.id)
        or not hmac.compare_digest(str(payload.get("cookie", "")), cookie_hash)
    ):
        raise HTTPException(400, "Google authorization does not match this browser")
    response = f"{google.get_google_redirect_uri()}?{urlencode(request.query_params.multi_items())}"
    try:
        google.save_callback_credentials(user, response, state=state)
    except Exception as exc:
        raise HTTPException(502, "Google authorization failed; check the server configuration") from exc
    queue_import(db, user)
    return HTMLResponse("<script>window.opener ? window.close() : window.location.href='/';</script>")


@router.get("/jobs")
def jobs(db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    rows = db.exec(
        select(SyncJob).where(SyncJob.user_id == user.id).order_by(SyncJob.created_at.desc()).limit(50)
    ).all()
    return [
        {"id": r.id, "action": r.action, "status": r.status, "error": r.error, "block_id": r.block_id}
        for r in rows
    ]


@router.post("/jobs/{job_id}/retry")
def retry(
    job_id: str, db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)
):
    row = db.exec(
        select(SyncJob).where(SyncJob.id == job_id, SyncJob.user_id == user.id).with_for_update()
    ).first()
    if not row:
        raise HTTPException(404, "Synchronization job not found")
    if row.status != "failed":
        raise HTTPException(409, "Only failed synchronization jobs can be retried")
    row.status, row.error, row.attempts, row.available_at = "queued", None, 0, utc_now()
    db.add(row)
    db.commit()
    return {"success": True, "status": "queued"}
