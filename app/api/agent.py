"""Asynchronous agent API. Calendar commands execute only in the durable worker."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.models import AgentMessage, AgentRun, AgentSession, User
from app.db.session import get_session
from app.schemas.agent import AgentChatRequest, AgentDecisionRequest, ResumeRequest
from app.services import auth_service, run_service

router = APIRouter(prefix="/api", tags=["agents"])


def translate(callback):
    try:
        return callback()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/agent/chat", status_code=202)
@router.post("/chat", status_code=202, include_in_schema=False)
def chat(
    data: AgentChatRequest,
    db: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    return translate(lambda: run_service.describe(db, run_service.enqueue(db, user, data)))


@router.get("/agent/runs/{run_id}")
def get_run(
    run_id: str,
    cursor: int = 0,
    db: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    return translate(
        lambda: run_service.describe(db, run_service.owned(db, AgentRun, run_id, user), max(0, cursor))
    )


@router.post("/agent/runs/{run_id}/resume", status_code=202)
def resume(
    run_id: str,
    data: ResumeRequest,
    db: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    return translate(
        lambda: run_service.describe(
            db,
            run_service.resume(
                db, user, run_id, data.interrupt_id, {"answer": data.response}, data.request_id
            ),
        )
    )


@router.post("/agent/runs/{run_id}/cancel")
def cancel(
    run_id: str, db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)
):
    return translate(lambda: run_service.describe(db, run_service.cancel(db, user, run_id)))


@router.post("/agent/confirm", status_code=202)
@router.post("/chat/accept", status_code=202, include_in_schema=False)
def confirm(
    data: AgentDecisionRequest,
    db: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    return translate(
        lambda: run_service.describe(
            db, run_service.decision(db, user, data.session_id, data.draft_id, data.revision, True)
        )
    )


@router.post("/agent/reject", status_code=202)
@router.post("/chat/reject", status_code=202, include_in_schema=False)
def reject(
    data: AgentDecisionRequest,
    db: Session = Depends(get_session),
    user: User = Depends(auth_service.get_current_user),
):
    return translate(
        lambda: run_service.describe(
            db, run_service.decision(db, user, data.session_id, data.draft_id, data.revision, False)
        )
    )


@router.post("/agent/new-session")
def new_session(db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    row = AgentSession(user_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"session_id": row.id, "calendar_snapshot": ""}


@router.get("/agent/sessions")
def sessions(db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    rows = db.exec(
        select(AgentSession)
        .where(AgentSession.user_id == user.id)
        .order_by(AgentSession.last_accessed_at.desc())
    ).all()
    return [
        {
            "session_id": r.id,
            "title": r.title,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "last_accessed_at": r.last_accessed_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


@router.get("/agent/sessions/{session_id}/messages")
def messages(
    session_id: str, db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)
):
    translate(lambda: run_service.owned(db, AgentSession, session_id, user))
    rows = db.exec(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id, AgentMessage.user_id == user.id)
        .order_by(AgentMessage.id.desc())
        .limit(200)
    ).all()
    return [
        {"role": row.role, "content": row.content, "created_at": row.created_at.isoformat()}
        for row in reversed(rows)
    ]


@router.get("/agent/sessions/{session_id}/runs")
def session_runs(
    session_id: str, db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)
):
    translate(lambda: run_service.owned(db, AgentSession, session_id, user))
    rows = db.exec(
        select(AgentRun)
        .where(AgentRun.session_id == session_id, AgentRun.user_id == user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(20)
    ).all()
    return [run_service.describe(db, row) for row in rows]


@router.get("/agent/drafts")
def drafts(db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    from app.db.models import Draft

    rows = db.exec(select(Draft).where(Draft.user_id == user.id, Draft.status == "pending")).all()
    return [
        {
            "id": row.id,
            "revision": row.revision,
            "run_id": row.run_id,
            "session_id": db.get(AgentRun, row.run_id).session_id,
            "preview": row.preview,
        }
        for row in rows
    ]


@router.post("/agent/runs/{run_id}/retry", status_code=202)
def retry(
    run_id: str, db: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)
):
    row = translate(lambda: run_service.owned(db, AgentRun, run_id, user))
    row = db.exec(select(AgentRun).where(AgentRun.id == row.id).with_for_update()).one()
    if row.status != "failed":
        raise HTTPException(409, "Only failed runs can be retried")
    row.status, row.error = "queued", None
    db.add(row)
    db.commit()
    return run_service.describe(db, row)
