import json

from sqlmodel import Session, select

from app.db.models import EvalRun, User


def create_eval_run(session: Session, user: User | None, name: str, input_prompt: str = "", expected=None, result=None, metrics=None) -> EvalRun:
    run = EvalRun(
        user_id=user.id if user else None,
        name=name,
        input_prompt=input_prompt,
        expected_json=json.dumps(expected or {}),
        result_json=json.dumps(result or {}),
        metrics_json=json.dumps(metrics or {}),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def list_eval_runs(session: Session, user: User | None) -> list[EvalRun]:
    if user:
        return list(session.exec(select(EvalRun).where(EvalRun.user_id == user.id).order_by(EvalRun.created_at.desc())).all())
    return list(session.exec(select(EvalRun).order_by(EvalRun.created_at.desc())).all())

