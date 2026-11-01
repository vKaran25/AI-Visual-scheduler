"""Explicit memories and separately approved cross-session suggestions."""

from sqlmodel import select

from app.db.models import AgentSession, Memory, MemoryProposal


def list_prefs(session, user):
    return list(
        session.exec(
            select(Memory)
            .where(Memory.user_id == user.id, Memory.type == "pref")
            .order_by(Memory.created_at.desc())
        ).all()
    )


def list_memories(session, user):
    return list(
        session.exec(select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at.desc())).all()
    )


def create_memory(session, user, memory_type, content, chat_session_id=None):
    memory_type = "pref" if memory_type == "preference" else memory_type
    content = content.strip()
    if memory_type not in ("pref", "fact") or not content:
        raise ValueError("A nonempty pref or fact is required")
    if memory_type == "fact":
        conversation = session.get(AgentSession, chat_session_id) if chat_session_id else None
        if not conversation or conversation.user_id != user.id:
            raise ValueError("Facts require a conversation owned by you")
    elif chat_session_id:
        raise ValueError("Permanent preferences cannot be tied to a conversation")
    row = Memory(user_id=user.id, type=memory_type, content=content, chat_session_id=chat_session_id)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_memory(session, user, memory_id):
    row = session.get(Memory, memory_id)
    if not row or row.user_id != user.id:
        return False
    session.delete(row)
    session.commit()
    return True


def decide_proposal(session, user, proposal_id, accept):
    proposal = session.exec(
        select(MemoryProposal)
        .where(MemoryProposal.id == proposal_id, MemoryProposal.user_id == user.id)
        .with_for_update()
    ).first()
    if not proposal:
        raise LookupError("Memory suggestion not found")
    if proposal.status == "pending":
        if (
            accept
            and not session.exec(
                select(Memory).where(
                    Memory.user_id == user.id, Memory.type == "pref", Memory.content == proposal.content
                )
            ).first()
        ):
            session.add(Memory(user_id=user.id, type="pref", content=proposal.content))
        proposal.status = "accepted" if accept else "rejected"
        session.add(proposal)
        session.commit()
    return {"id": proposal.id, "status": proposal.status}
