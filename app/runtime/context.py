"""Trusted execution identity; model-generated state never supplies authorization."""

from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.core.config import ACTIVE_RUN_SECONDS, MAX_MODEL_ATTEMPTS
from app.db.models import AgentRun, RunArtifact, RunEvent, utc_now
from app.db.session import engine


class LeaseLost(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class Execution:
    run_id: str
    user_id: int
    session_id: str
    lease_token: str


_current: ContextVar[Execution] = ContextVar("calendar_execution")


def current() -> Execution:
    return _current.get()


def bind(execution: Execution):
    return _current.set(execution)


def unbind(token):
    _current.reset(token)


def fence(db: Session) -> AgentRun:
    identity = current()
    run = db.exec(
        select(AgentRun)
        .where(AgentRun.id == identity.run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if (
        run.user_id != identity.user_id
        or run.lease_token != identity.lease_token
        or not run.lease_until
        or run.lease_until <= utc_now()
    ):
        raise LeaseLost("This worker no longer owns the run")
    if run.cancel_requested:
        raise LeaseLost("Run was cancelled")
    if run.active_seconds >= ACTIVE_RUN_SECONDS:
        raise BudgetExhausted("Active execution deadline reached")
    return run


def event(stage: str, **details):
    with Session(engine) as db:
        run = fence(db)
        run.stage = stage
        run.updated_at = utc_now()
        db.add(run)
        db.add(RunEvent(run_id=run.id, stage=stage, details=details))
        db.commit()


def reserve_attempt():
    with Session(engine) as db:
        run = fence(db)
        if run.model_attempts >= MAX_MODEL_ATTEMPTS:
            raise BudgetExhausted("Free-model request budget reached; please retry with a narrower request")
        run.model_attempts += 1
        db.add(run)
        db.commit()


def artifact(key: str):
    with Session(engine) as db:
        fence(db)
        row = db.exec(
            select(RunArtifact).where(RunArtifact.run_id == current().run_id, RunArtifact.key == key)
        ).first()
        return row.payload if row else None


def save_artifact(key: str, kind: str, payload: dict):
    with Session(engine) as db:
        fence(db)
        stmt = insert(RunArtifact).values(
            run_id=current().run_id, key=key, kind=kind, payload=payload, created_at=utc_now()
        )
        db.execute(
            stmt.on_conflict_do_update(constraint="uq_artifact_key", set_={"payload": payload, "kind": kind})
        )
        db.commit()
