from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.models import User
from app.db.session import get_session
from app.services import auth_service, eval_service

router = APIRouter(prefix="/api/evals", tags=["evals"])


@router.get("/runs")
def list_runs(session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return eval_service.list_eval_runs(session, user)


@router.post("/run")
def create_run(data: dict, session: Session = Depends(get_session), user: User = Depends(auth_service.get_current_user)):
    return eval_service.create_eval_run(
        session,
        user,
        name=data.get("name", "manual-eval"),
        input_prompt=data.get("input_prompt", ""),
        expected=data.get("expected", {}),
        result=data.get("result", {}),
        metrics=data.get("metrics", {}),
    )

