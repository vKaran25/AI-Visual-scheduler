from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
)
from app.db.models import User
from app.db.session import get_session

AUTH_COOKIE = "access_token"
SIGN_UP_FAILED_MESSAGE = "Could not create the account. If you already have one, sign in instead."
password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return password_hash.verify(password, hashed_password)
    except UnknownHashError:
        return False


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    """A real hash of a random value, verified against when no account matches, so timing does not reveal emails."""
    return hash_password(datetime.now(timezone.utc).isoformat())


def create_access_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "exp": expires,
        "type": "access",
        "ver": user.token_version,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE,
        token,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        AUTH_COOKIE,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        path="/",
    )


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email.lower())).first()


def create_user(session: Session, email: str, password: str) -> User:
    # Hash before the lookup so a taken email takes as long to answer as a new one.
    digest = hash_password(password)
    if get_user_by_email(session, email):
        raise ValueError(SIGN_UP_FAILED_MESSAGE)
    user = User(email=email.lower(), password_hash=digest)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:  # a concurrent sign-up with the same email won the unique index
        session.rollback()
        raise ValueError(SIGN_UP_FAILED_MESSAGE) from exc
    session.refresh(user)
    return user


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(session, email)
    if not user:
        verify_password(password, _decoy_hash())
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def _user_from_token(session: Session, token: str) -> User:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.isdigit():
            raise ValueError("Invalid user ID")
        user_id = int(subject)
        version = payload.get("ver")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not isinstance(version, int) or version != user.token_version:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    token = request.cookies.get(AUTH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    return _user_from_token(session, token)


def revoke_sessions(session: Session, user: User) -> None:
    """Invalidate every token issued to this account, on every device."""
    user.token_version += 1
    session.add(user)
    session.commit()


def revoke_request_session(request: Request, session: Session) -> None:
    """On logout, revoke the account if the presented cookie is a valid session. Invalid cookies are ignored."""
    token = request.cookies.get(AUTH_COOKIE)
    if not token:
        return
    try:
        user = _user_from_token(session, token)
    except HTTPException:
        return
    revoke_sessions(session, user)
