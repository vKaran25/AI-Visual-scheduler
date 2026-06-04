from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db.models import Memory, User


def list_memories(session: Session, user: User) -> list[Memory]:
    return list(session.exec(select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at.desc())).all())


def create_memory(session: Session, user: User, memory_type: str, content: str) -> Memory:
    memory = Memory(user_id=user.id, type=memory_type, content=content)
    session.add(memory)
    session.commit()
    session.refresh(memory)
    return memory


def delete_memory(session: Session, user: User, memory_id: int) -> bool:
    memory = session.get(Memory, memory_id)
    if not memory or memory.user_id != user.id:
        return False
    session.delete(memory)
    session.commit()
    return True


def retrieve_memories(session: Session, user: User, query: str, limit: int = 8) -> list[Memory]:
    terms = [term.lower() for term in query.split() if len(term) > 2]
    memories = list_memories(session, user)
    ranked = []
    for memory in memories:
        score = sum(1 for term in terms if term in memory.content.lower() or term in memory.type.lower())
        if score:
            memory.last_used_at = datetime.now(timezone.utc)
            session.add(memory)
        ranked.append((score, memory.created_at, memory))
    session.commit()
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [memory for _, _, memory in ranked[:limit]]

