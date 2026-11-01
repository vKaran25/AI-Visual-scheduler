"""Fresh read context and idempotent graph-side artifacts."""

import hashlib
from datetime import timedelta

from sqlmodel import Session, select

from app.db.models import AgentMessage, AgentSession, GoogleConnection, Memory, MemoryProposal, User
from app.db.session import engine
from app.domain.time import local_now
from app.integrations import google
from app.runtime import context as execution
from app.services import preset_service, scheduler_service


def snapshot(refresh=True):
    identity = execution.current()
    with Session(engine, expire_on_commit=False) as db:
        run = execution.fence(db)
        user = db.get(User, identity.user_id)
        conversation = db.get(AgentSession, identity.session_id)
        if conversation.user_id != user.id:
            raise ValueError("Conversation ownership mismatch")
        db.commit()
        if refresh and db.get(GoogleConnection, user.id):
            if not google.sync_gcal_events(db, user, force=True):
                raise ValueError("Google availability could not be refreshed; retry before scheduling")
        history = list(
            db.exec(
                select(AgentMessage)
                .where(AgentMessage.user_id == user.id, AgentMessage.session_id == conversation.id)
                .order_by(AgentMessage.id.desc())
                .limit(20)
            ).all()
        )
        return {
            "answers": run.input.get("answers", []),
            "now": local_now(user.timezone).isoformat(),
            "timezone": user.timezone,
            "timezone_confirmed": user.timezone_confirmed,
            "calendar_revision": user.calendar_revision,
            "calendar": [
                scheduler_service.block_to_dict(b) for b in scheduler_service.user_blocks(db, user.id)
            ],
            "presets": preset_service.list_presets(db, user),
            "facts": conversation.facts,
            "summary": conversation.summary,
            "preferences": [
                m.content
                for m in db.exec(select(Memory).where(Memory.user_id == user.id, Memory.type == "pref")).all()
            ],
            "messages": [{"role": m.role, "content": m.content} for m in reversed(history)],
        }


def message(key, content):
    identity = execution.current()
    with Session(engine) as db:
        execution.fence(db)
        if not db.exec(select(AgentMessage).where(AgentMessage.operation_key == key)).first():
            db.add(
                AgentMessage(
                    user_id=identity.user_id,
                    session_id=identity.session_id,
                    role="assistant",
                    content=content,
                    operation_key=key,
                )
            )
            db.commit()


def remember_understanding(understanding, turn):
    identity = execution.current()
    with Session(engine) as db:
        execution.fence(db)
        conversation = db.get(AgentSession, identity.session_id)
        conversation.facts = understanding.constraints.model_dump(mode="json")
        conversation.title = understanding.title
        if understanding.summary:
            conversation.summary = understanding.summary
        db.add(conversation)
        from sqlalchemy.dialects.postgresql import insert

        from app.db.models import new_id, utc_now

        for content in understanding.memory_suggestions:
            source = (
                "memory:"
                + str(identity.user_id)
                + ":"
                + hashlib.sha256(content.strip().lower().encode()).hexdigest()
            )
            statement = insert(MemoryProposal).values(
                id=new_id(),
                user_id=identity.user_id,
                content=content,
                status="pending",
                source_key=source,
                created_at=utc_now(),
            )
            db.execute(statement.on_conflict_do_nothing(index_elements=["source_key"]))
        db.commit()


def busy_instants(db, user, constraints):
    blocks = scheduler_service.user_blocks(db, user.id)
    result = []
    for offset in range((constraints.end_date - constraints.start_date).days + 1):
        day = (constraints.start_date + timedelta(days=offset)).isoformat()
        for block in blocks:
            if scheduler_service.slot_applies_to_date(block, day):
                from app.domain.availability import occupied_instants

                first, last = occupied_instants(
                    {
                        **scheduler_service.block_to_dict(block),
                        "starts_at": block.starts_at,
                        "ends_at": block.ends_at,
                    },
                    day,
                    user.timezone,
                )
                result.append({"starts_at": first.isoformat(), "ends_at": last.isoformat()})
    return result
