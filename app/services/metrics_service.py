"""Tenant-scoped operational measurements from durable run artifacts."""

from collections import Counter, defaultdict

from sqlalchemy import func
from sqlmodel import select

from app.db.models import AgentRun, RunArtifact, RunEvent, SyncJob


def summary(db, user):
    runs = list(db.exec(select(AgentRun).where(AgentRun.user_id == user.id)).all())
    artifacts = list(
        db.exec(
            select(RunArtifact)
            .join(AgentRun, RunArtifact.run_id == AgentRun.id)
            .where(AgentRun.user_id == user.id)
            .order_by(RunArtifact.id.desc())
            .limit(5000)
        ).all()
    )
    reports = defaultdict(list)
    models = Counter()
    validations = Counter()
    optimizations = 0
    workers = 0
    for row in reversed(artifacts):
        if row.kind == "worker_result":
            workers += 1
        if row.kind == "validation_report":
            validations[row.payload["status"]] += 1
        if row.kind != "model_call":
            continue
        role = row.payload.get("role")
        models[row.payload.get("actual_model") or "unreported"] += 1
        if role == "optimizer":
            optimizations += 1
        if role == "evaluator":
            reports[row.run_id].append(row.payload["output"])

    def passed(report):
        return report["verdict"] == "pass" and not any(
            i["severity"] == "blocking" for i in report.get("issues", [])
        )

    improved = sum(
        len(values) > 1 and not passed(values[0]) and passed(values[-1]) for values in reports.values()
    )
    syncs = db.exec(
        select(SyncJob.status, func.count()).where(SyncJob.user_id == user.id).group_by(SyncJob.status)
    ).all()
    recovered = db.exec(
        select(func.count())
        .select_from(RunEvent)
        .join(AgentRun, RunEvent.run_id == AgentRun.id)
        .where(AgentRun.user_id == user.id, RunEvent.stage == "Recovered committed result")
    ).one()
    return {
        "runs": dict(Counter(r.status for r in runs)),
        "model_attempts": sum(r.model_attempts for r in runs),
        "active_seconds": round(sum(r.active_seconds for r in runs), 2),
        "successful_model_calls": dict(models),
        "worker_results": workers,
        "validation_reports": dict(validations),
        "optimization_rounds": optimizations,
        "evaluated_runs": len(reports),
        "repaired_to_pass": improved,
        "recovered_operations": recovered,
        "google_jobs": dict(syncs),
        "artifact_window": 5000,
    }
