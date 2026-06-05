from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.agents import roadmap_agent
from app.db.models import User
from app.db.session import get_session
from app.schemas.agent import AgentChatRequest, AgentDecisionRequest
from app.services import auth_service

router = APIRouter(prefix="/api", tags=["agents"])


@router.post("/agent/chat")
def agent_chat(data: AgentChatRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    try:
        return roadmap_agent.run_roadmap_agent(session, user, data.prompt, data.start_after, data.slack, data.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc


@router.post("/agent/confirm")
def agent_confirm(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return roadmap_agent.confirm_agent_plan(session, user, data.session_id)


@router.post("/agent/reject")
def agent_reject(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return roadmap_agent.reject_agent_plan(session, user, data.session_id)


@router.post("/chat")
def legacy_chat(data: AgentChatRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return agent_chat(data, session, user)


@router.post("/chat/accept")
def legacy_accept(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return agent_confirm(data, session, user)


@router.post("/chat/reject")
def legacy_reject(data: AgentDecisionRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return agent_reject(data, session, user)

