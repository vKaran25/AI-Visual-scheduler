from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlmodel import Session, select

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, COOKIE_SECURE, JWT_ALGORITHM, JWT_SECRET_KEY
from app.db.models import User
from app.db.session import get_session

AUTH_COOKIE = "access_token"
password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expires, "type": "access"}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE)


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email.lower())).first()


def create_user(session: Session, email: str, password: str) -> User:
    if get_user_by_email(session, email):
        raise ValueError("Email is already registered")
    user = User(email=email.lower(), password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(session, email)
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    token = request.cookies.get(AUTH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
