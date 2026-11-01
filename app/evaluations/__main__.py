"""python -m app.evaluations [--live]. Live tests use synthetic users and no calendar writes."""

import argparse
import json
from pathlib import Path


def metrics(rows):
    return {
        "cases": len(rows),
        "accuracy": sum(r["accepted"] == r["expected_accept"] for r in rows) / len(rows),
        "unsafe_acceptances": sum(r["accepted"] and not r["expected_accept"] for r in rows),
    }


def offline():
    from datetime import datetime, timezone

    from app.domain.contracts import Constraints, TaskSpec
    from app.domain.intervals import requested_minutes
    from app.domain.placement import place

    c = Constraints.model_validate(
        {
            "start_date": "2030-01-01",
            "end_date": "2030-01-01",
            "total_minutes": 60,
            "session_minutes": 30,
            "availability": [{"date": "2030-01-01", "start": "10:00", "end": "11:00"}],
        }
    )
    result = place(
        [
            TaskSpec(id="a", title="Read", duration_minutes=30),
            TaskSpec(id="b", title="Practice", duration_minutes=30, after=["a"]),
        ],
        c,
        [],
        "UTC",
        now=datetime(2029, 1, 1, tzinfo=timezone.utc),
    )
    return {
        "placement_status": result["status"],
        "placed_minutes": 60 if len(result["placements"]) == 2 else 0,
        "requested_1_1_hours_minutes": requested_minutes(1.1),
        "model_requests": 0,
    }


def live():
    import threading
    from datetime import timedelta

    from sqlmodel import Session

    from app.agents.prompts import EVALUATOR
    from app.db.models import AgentRun, AgentSession, EvalRun, User, new_id, utc_now
    from app.db.session import engine, verify_schema
    from app.domain.contracts import Evaluation
    from app.integrations.openrouter import generate
    from app.runtime import context
    from app.runtime.worker import heartbeat

    verify_schema()
    cases = json.loads((Path(__file__).with_name("cases.json")).read_text())
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            email=f"evaluation-{new_id()}@example.invalid", password_hash="disabled", timezone_confirmed=True
        )
        db.add(user)
        db.flush()
        conversation = AgentSession(user_id=user.id, title="Evaluator benchmark")
        db.add(conversation)
        db.flush()
        run = AgentRun(
            user_id=user.id,
            session_id=conversation.id,
            request_id=new_id(),
            status="running",
            graph_version="benchmark-v1",
            lease_token=new_id(),
            lease_until=utc_now() + timedelta(seconds=90),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        job = run.model_dump()
    token = context.bind(context.Execution(run.id, user.id, conversation.id, run.lease_token))
    stop = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(job, stop), daemon=True)
    thread.start()
    rows = []
    try:
        for index, case in enumerate(cases):
            report = generate(
                "evaluator",
                EVALUATOR,
                {"candidate_revision": str(index), **case},
                Evaluation,
                f"benchmark:{index}",
            )
            accepted = report.verdict == "pass" and not any(i.severity == "blocking" for i in report.issues)
            rows.append(
                {
                    "name": case["name"],
                    "expected_accept": case["expected_accept"],
                    "accepted": accepted,
                    "report": report.model_dump(),
                }
            )
        result = metrics(rows)
        with Session(engine) as db:
            db.add(
                EvalRun(
                    user_id=user.id,
                    name="labeled-evaluator",
                    expected_json=json.dumps(cases),
                    result_json=json.dumps(rows),
                    metrics_json=json.dumps(result),
                )
            )
            run = db.get(AgentRun, run.id)
            run.status = "completed"
            run.lease_token = None
            run.lease_until = None
            db.add(run)
            db.commit()
        return {**result, "results": rows}
    finally:
        stop.set()
        thread.join(timeout=10)
        context.unbind(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live", action="store_true", help="Use configured free OpenRouter models on synthetic labeled cases"
    )
    args = parser.parse_args()
    print(json.dumps(live() if args.live else offline(), indent=2))
