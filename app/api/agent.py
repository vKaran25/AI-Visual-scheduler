import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import column
from sqlmodel import Session, select

from app.agents import roadmap_agent
from app.db.models import AgentMessage, AgentSession, User
from app.db.session import get_session
from app.schemas.agent import AgentChatRequest, AgentDecisionRequest
from app.services import auth_service, memory_service

router = APIRouter(prefix="/api", tags=["agents"])
logger = logging.getLogger(__name__)


@router.post("/agent/chat")
def agent_chat(data: AgentChatRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    try:
        return roadmap_agent.run_roadmap_agent(session, user, data.prompt, data.start_after, data.slack, data.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent chat failed for user %s", user.id)
        raise HTTPException(status_code=500, detail="Agent could not complete this request; please try again") from exc


@router.post("/agent/confirm")
def agent_confirm(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return roadmap_agent.confirm_agent_plan(session, user, data.session_id, data.draft_id)


@router.post("/agent/reject")
def agent_reject(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return roadmap_agent.reject_agent_plan(session, user, data.session_id, data.draft_id)


@router.post("/agent/new-session")
def agent_new_session(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    """Create a blank new planning session. Returns its ID + a fresh calendar snapshot."""
    if user.id is None:
        raise HTTPException(status_code=401, detail="User is not saved")
    session_id = uuid4().hex
    cal_snapshot = memory_service.get_calendar_snapshot(session, user)
    db_session = AgentSession(
        id=session_id,
        user_id=user.id,
        prompt="",
        status="active",
        title="New Session",
        calendar_snapshot=cal_snapshot,
    )
    session.add(db_session)
    session.commit()
    return {
        "session_id": session_id,
        "calendar_snapshot": cal_snapshot,
    }


@router.get("/agent/sessions")
def list_agent_sessions(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    """Return all past planning sessions for this user, newest first."""
    rows = list(
        session.exec(
            select(AgentSession)
            .where(AgentSession.user_id == user.id)
            .order_by(AgentSession.created_at.desc())
        ).all()
    )
    return [
        {
            "session_id": row.id,
            "title": row.title or row.prompt[:60] or "Untitled",
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "last_accessed_at": row.last_accessed_at.isoformat() if row.last_accessed_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
        for row in rows
    ]


@router.get("/agent/sessions/{session_id}/messages")
def get_agent_session_messages(
    session_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    owned = session.get(AgentSession, session_id)
    if not owned or owned.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    rows = session.exec(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id, AgentMessage.user_id == user.id)
        .order_by(column("id").desc())
        .limit(200)
    ).all()
    return [
        {"role": row.role, "content": row.content, "created_at": row.created_at.isoformat()}
        for row in reversed(rows)
    ]


# ── Legacy aliases (keep for backward compatibility) ──────────────────────

@router.post("/chat")
def legacy_chat(data: AgentChatRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return agent_chat(data, session, user)


@router.post("/chat/accept")
def legacy_accept(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return agent_confirm(data, session, user)


@router.post("/chat/reject")
def legacy_reject(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return agent_reject(data, session, user)
