"""Authenticated run commands; every public lookup is scoped to its owner."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.config import GRAPH_VERSION
from app.db.models import AgentMessage, AgentRun, AgentSession, Draft, RunEvent, new_id, utc_now

LIVE = ("queued", "running", "awaiting_input", "awaiting_approval")


def owned(db, model, record_id, user):
    row = db.get(model, record_id)
    if not row or row.user_id != user.id:
        raise LookupError("Not found")
    return row


def describe(db, run, cursor=0):
    events = list(
        db.exec(
            select(RunEvent)
            .where(RunEvent.run_id == run.id, RunEvent.id > cursor)
            .order_by(RunEvent.id)
            .limit(100)
        ).all()
    )
    draft = db.exec(
        select(Draft)
        .where(Draft.run_id == run.id, Draft.status == "pending")
        .order_by(Draft.created_at.desc())
    ).first()
    return {
        "run_id": run.id,
        "session_id": run.session_id,
        "status": run.status,
        "stage": run.stage,
        "pending": run.pending,
        "result": run.result,
        "error": run.error,
        "draft": {"id": draft.id, "revision": draft.revision, "preview": draft.preview} if draft else None,
        "events": [{"id": e.id, "stage": e.stage, "details": e.details} for e in events],
        "cursor": events[-1].id if events else cursor,
        "metrics": {"model_attempts": run.model_attempts, "active_seconds": run.active_seconds},
    }


def enqueue(db, user, request):
    request_id = request.request_id or new_id()
    previous = db.exec(
        select(AgentRun).where(AgentRun.user_id == user.id, AgentRun.request_id == request_id)
    ).first()
    if previous:
        return previous
    if request.session_id:
        conversation = owned(db, AgentSession, request.session_id, user)
        db.exec(select(AgentSession).where(AgentSession.id == conversation.id).with_for_update()).one()
        active = db.exec(
            select(AgentRun).where(AgentRun.session_id == conversation.id, AgentRun.status.in_(LIVE))
        ).first()
        if active:
            raise ValueError(
                "This conversation has an active run. Resume or cancel it before sending another request."
            )
    else:
        conversation = AgentSession(user_id=user.id, prompt=request.prompt, title=request.prompt[:60])
        db.add(conversation)
        db.flush()
    run = AgentRun(
        user_id=user.id,
        session_id=conversation.id,
        request_id=request_id,
        graph_version=GRAPH_VERSION,
        input={
            "prompt": request.prompt,
            "start_after": request.start_after,
            "slack": request.slack,
            "turn": new_id(),
        },
    )
    db.add(run)
    db.flush()
    db.add(
        AgentMessage(
            user_id=user.id,
            session_id=conversation.id,
            role="user",
            content=request.prompt,
            operation_key=f"request:{user.id}:{request_id}",
        )
    )
    conversation.last_accessed_at = utc_now()
    conversation.status = "active"
    conversation.finished_at = None
    db.add(conversation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.exec(
            select(AgentRun).where(AgentRun.user_id == user.id, AgentRun.request_id == request_id)
        ).first()
        if previous:
            return previous
        raise ValueError("Another run started in this conversation") from None
    db.refresh(run)
    return run


def resume(db, user, run_id, interrupt_id, value, request_id):
    run = db.exec(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id).with_for_update()
    ).first()
    if not run:
        raise LookupError("Run not found")
    if run.input.get("resume_request_id") == request_id:
        return run
    if (
        run.status not in ("awaiting_input", "awaiting_approval")
        or run.pending.get("interrupt_id") != interrupt_id
    ):
        raise ValueError("This question or approval is no longer current")
    run.input = {**run.input, "resume": value, "resume_request_id": request_id}
    if isinstance(value, dict) and value.get("answer"):
        run.input = {**run.input, "answers": run.input.get("answers", []) + [value["answer"]]}
    run.status, run.error, run.stage = "queued", None, "Queued"
    run.lease_token, run.lease_until = None, None
    # A new human answer starts a new turn budget. Retries without an answer do not.
    if isinstance(value, dict) and value.get("answer"):
        run.model_attempts, run.active_seconds = 0, 0
        db.add(
            AgentMessage(
                user_id=user.id,
                session_id=run.session_id,
                role="user",
                content=value["answer"],
                operation_key=f"resume:{user.id}:{request_id}",
            )
        )
    run.updated_at = utc_now()
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def decision(db, user, session_id, draft_id, revision, accept):
    draft = owned(db, Draft, draft_id, user)
    run = owned(db, AgentRun, draft.run_id, user)
    if (
        run.session_id == session_id
        and draft.revision == revision
        and draft.status == ("confirmed" if accept else "rejected")
    ):
        return run
    if run.session_id != session_id or draft.revision != revision or draft.status != "pending":
        raise ValueError("This draft was replaced; review the latest preview")
    request_id = f"decision:{draft_id}:{revision}:{accept}"
    if run.input.get("resume_request_id") == request_id:
        return run
    if (
        run.status != "awaiting_approval"
        or run.pending.get("kind") != "approval"
        or run.pending.get("draft_id") != draft_id
        or run.pending.get("revision") != revision
    ):
        raise ValueError("This draft is no longer awaiting approval")
    return resume(
        db,
        user,
        run.id,
        run.pending.get("interrupt_id"),
        {"decision": "accept" if accept else "reject", "draft_id": draft_id, "revision": revision},
        f"decision:{draft_id}:{revision}:{accept}",
    )


def cancel(db, user, run_id):
    run = db.exec(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id).with_for_update()
    ).first()
    if not run:
        raise LookupError("Run not found")
    if run.status in ("completed", "failed", "cancelled"):
        return run  # finished runs keep their outcome
    run.cancel_requested = True
    if run.status != "running":
        run.status = "cancelled"
    for draft in db.exec(select(Draft).where(Draft.run_id == run.id, Draft.status == "pending")).all():
        draft.status = "cancelled"
        db.add(draft)
    db.add(run)
    db.commit()
    return run
