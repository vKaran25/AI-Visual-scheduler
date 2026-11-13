"""Spoken conversation endpoint. Speech recognition and synthesis happen in the browser."""

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.integrations.openrouter import ModelUnavailable
from app.services import auth_service, voice_agent

router = APIRouter(prefix="/api/voice", tags=["voice"])
TURNS_PER_MINUTE = 20
_recent: dict[int, deque] = defaultdict(deque)


class VoiceTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)
    request_id: str = Field(min_length=8, max_length=128)


def _rate_limit(user_id: int) -> None:
    now, window = time.monotonic(), _recent[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= TURNS_PER_MINUTE:
        raise HTTPException(429, "You're talking faster than I can keep up. Wait a moment and try again.")
    window.append(now)


@router.post("/turn")
def voice_turn(
    data: VoiceTurnRequest,
    db: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    _rate_limit(user.id)
    try:
        return voice_agent.turn(db, user, data.transcript.strip(), data.session_id, data.request_id)
    except LookupError as exc:
        raise HTTPException(404, "Conversation not found") from exc
    except ModelUnavailable:
        return {
            "session_id": data.session_id,
            "say": "I can't reach the AI right now. You can still type your request or use Fill details.",
            "action": "none",
            "run": None,
        }
