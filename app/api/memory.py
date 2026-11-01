from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.schemas.agent import MemoryDecisionRequest
from app.schemas.memory import MemoryRequest
from app.services import auth_service, memory_service

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory")
def list_memory(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return memory_service.list_memories(session, user)


@router.post("/memory")
def create_memory(
    data: MemoryRequest,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    try:
        return memory_service.create_memory(session, user, data.type, data.content, data.chat_session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/memory/{memory_id}")
def delete_memory(
    memory_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    memory_service.delete_memory(session, user, memory_id)
    return {"success": True}


@router.get("/memory-proposals")
def proposals(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    from sqlmodel import select

    from app.db.models import MemoryProposal

    return session.exec(
        select(MemoryProposal).where(MemoryProposal.user_id == user.id, MemoryProposal.status == "pending")
    ).all()


@router.post("/memory-proposals/{proposal_id}/decision")
def proposal_decision(
    proposal_id: str,
    data: MemoryDecisionRequest,
    session: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    try:
        return memory_service.decide_proposal(session, user, proposal_id, data.accept)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
