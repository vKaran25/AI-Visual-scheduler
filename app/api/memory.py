from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.schemas.memory import MemoryRequest
from app.services import auth_service, memory_service

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory")
def list_memory(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return memory_service.list_memories(session, user)


@router.post("/memory")
def create_memory(data: MemoryRequest, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return memory_service.create_memory(session, user, data.type, data.content)


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: int, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    memory_service.delete_memory(session, user, memory_id)
    return {"success": True}

