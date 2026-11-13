"""Exercise the real LangGraph/checkpointer with deterministic provider outputs."""

from sqlmodel import select

from app.db.models import AgentRun, Block, Draft, OperationOutcome
from app.domain.contracts import Evaluation, RepairPlan, Understanding, WorkerOutput, WorkOrder
from app.runtime.worker import claim, run_once
from app.schemas.agent import AgentChatRequest
from app.services import run_service, scheduler_service


def setup_model(monkeypatch, *, repair=False, missing=False, conflict=False):
    counts = {}
    order = WorkOrder(id="plan", worker="planning", objective="Python practice", duration_budget=120)
    constraints = {
        "start_date": "2030-01-01",
        "end_date": "2030-01-02",
        "total_minutes": 120,
        "session_minutes": 60,
        "availability": [{"date": "2030-01-01", "start": "10:00", "end": "12:00"}],
    }

    def generate(role, prompt, data, output_type, cache_key):
        counts[role] = counts.get(role, 0) + 1
        if role == "orchestrator":
            return Understanding(
                intent="plan",
                constraints=constraints,
                work_orders=[order],
                missing=["which subject to study"] if missing and counts[role] == 1 else [],
            )
        if role == "planning":
            title = "Practice with examples" if counts[role] > 1 else "Python basics"
            return WorkerOutput(
                tasks=[
                    {"id": "plan-a", "title": title, "duration_minutes": 60},
                    {"id": "plan-b", "title": "Exercises", "duration_minutes": 60, "after": ["plan-a"]},
                ]
            )
        if role == "evaluator":
            revise = repair and counts[role] == 1
            return Evaluation(
                candidate_revision=data["candidate_revision"],
                verdict="revise" if revise else "pass",
                explanation="Add concrete practice" if revise else "Complete",
                issues=[
                    {
                        "id": "specificity",
                        "severity": "blocking",
                        "task_ids": ["plan"],
                        "evidence": "Generic task title",
                        "required_fix": "Make practice concrete",
                    }
                ]
                if revise
                else [],
            )
        if role == "optimizer":
            return RepairPlan(repairs=[order])
        raise AssertionError(role)

    monkeypatch.setattr("app.integrations.openrouter.generate", generate)
    return counts


def enqueue(db, user, prompt="Plan Python"):
    return run_service.enqueue(
        db, user, AgentChatRequest(prompt=prompt, request_id=__import__("uuid").uuid4().hex)
    )


def reload(db, run):
    db.expire_all()
    return db.get(AgentRun, run.id)


def test_combined_graph_repairs_then_waits_for_approval(db, user, graph, monkeypatch):
    counts = setup_model(monkeypatch, repair=True)
    run = enqueue(db, user)
    assert run_once(graph)
    run = reload(db, run)
    assert run.status == "awaiting_approval", run.error
    assert counts["optimizer"] == 1 and counts["planning"] == 2 and counts["evaluator"] == 2
    assert not db.exec(select(Block)).all()
    draft = db.exec(select(Draft).where(Draft.run_id == run.id, Draft.status == "pending")).one()
    assert "Practice" in draft.preview["scheduled"][0]["label"]
    free = scheduler_service.compute_free_blocks(db, user, "2030-01-01T10:00", 2, max_days=1)
    assert free["allocated"][0]["start"] == "10:00"
    run_service.decision(db, user, run.session_id, draft.id, draft.revision, True)
    assert run_once(graph)
    run = reload(db, run)
    assert run.status == "completed", run.error
    assert len(db.exec(select(Block)).all()) == 2
    assert db.exec(select(OperationOutcome)).one().result["success"]


def test_clarification_resumes_without_reasking(db, user, graph, monkeypatch):
    counts = setup_model(monkeypatch, missing=True)
    run = enqueue(db, user)
    run_once(graph)
    run = reload(db, run)
    assert run.status == "awaiting_input", run.error
    run_service.resume(db, user, run.id, run.pending["interrupt_id"], {"answer": "10 AM to noon"}, "answer-1")
    run_once(graph)
    run = reload(db, run)
    assert run.status == "awaiting_approval", run.error
    assert counts["orchestrator"] == 2


def test_stale_calendar_conflict_cannot_commit(db, user, graph, monkeypatch):
    setup_model(monkeypatch)
    run = enqueue(db, user)
    run_once(graph)
    run = reload(db, run)
    assert run.status == "awaiting_approval", run.error
    draft = db.exec(select(Draft).where(Draft.run_id == run.id, Draft.status == "pending")).one()
    scheduler_service.create_block(
        db, user, {"date": "2030-01-01", "start": "10:00", "end": "11:00", "label": "New meeting"}
    )
    run_service.decision(db, user, run.session_id, draft.id, draft.revision, True)
    run_once(graph)
    run = reload(db, run)
    assert run.status == "awaiting_input", run.error
    assert len(db.exec(select(Block)).all()) == 1


def test_duplicate_requests_rejection_and_ownership(db, user, graph, monkeypatch):
    setup_model(monkeypatch)
    request = AgentChatRequest(prompt="Plan", request_id="duplicate")
    a = run_service.enqueue(db, user, request)
    b = run_service.enqueue(db, user, request)
    assert a.id == b.id
    run_once(graph)
    a = reload(db, a)
    draft = db.exec(select(Draft).where(Draft.run_id == a.id, Draft.status == "pending")).one()
    run_service.decision(db, user, a.session_id, draft.id, draft.revision, False)
    run_once(graph)
    assert reload(db, a).status == "completed"
    assert not db.exec(select(Block)).all()


def test_restart_after_commit_replays_outcome_not_calendar(db, user, graph, monkeypatch):
    setup_model(monkeypatch)
    run = enqueue(db, user)
    run_once(graph)
    run = reload(db, run)
    draft = db.exec(select(Draft).where(Draft.run_id == run.id, Draft.status == "pending")).one()
    run_service.decision(db, user, run.session_id, draft.id, draft.revision, True)
    # Crash the checkpoint write immediately after the domain commit.
    saver = graph.checkpointer
    original = saver.put
    crashed = {"value": False}

    def put(*args, **kwargs):
        with __import__("sqlmodel").Session(
            __import__("app.db.session", fromlist=["engine"]).engine
        ) as other:
            committed = other.exec(select(OperationOutcome)).first()
        if committed and not crashed["value"]:
            crashed["value"] = True
            raise RuntimeError("simulated checkpoint failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(saver, "put", put)
    run_once(graph)
    run = reload(db, run)
    assert crashed["value"]
    assert len(db.exec(select(Block)).all()) == 2
    run.status = "queued"
    db.add(run)
    db.commit()
    run_once(graph)
    run = reload(db, run)
    assert run.status == "completed", run.error
    assert len(db.exec(select(Block)).all()) == 2


def test_expired_worker_cannot_write_checkpoint_or_artifact(db, user, graph):
    from app.runtime import context

    run = enqueue(db, user)
    job = claim()
    run = reload(db, run)
    run.lease_token = "replacement-worker"
    db.add(run)
    db.commit()
    identity = context.Execution(job["id"], user.id, job["session_id"], job["lease_token"])
    token = context.bind(identity)
    try:
        import pytest

        with pytest.raises(context.LeaseLost):
            context.save_artifact("stale", "test", {"value": 1})
        with pytest.raises(context.LeaseLost):
            context.reserve_attempt()
    finally:
        context.unbind(token)


def test_no_progress_optimizer_stops(db, user, graph, monkeypatch):
    setup_model(monkeypatch)
    original = __import__("app.integrations.openrouter", fromlist=["generate"]).generate

    def generate(role, prompt, data, output_type, cache_key):
        if role == "evaluator":
            return Evaluation(
                candidate_revision=data["candidate_revision"],
                verdict="revise",
                issues=[
                    {
                        "id": "quality",
                        "severity": "blocking",
                        "task_ids": ["plan"],
                        "evidence": "Still vague",
                        "required_fix": "Improve",
                    }
                ],
                explanation="Revise",
            )
        return original(role, prompt, data, output_type, cache_key)

    monkeypatch.setattr("app.integrations.openrouter.generate", generate)
    run = enqueue(db, user)
    run_once(graph)
    run = reload(db, run)
    assert run.status == "awaiting_input", run.error
    assert not db.exec(select(Draft)).all()


def test_preset_draft_is_atomic_and_confirmation_is_idempotent(db, user):
    from app.domain.contracts import Action
    from app.runtime import context
    from app.services import draft_service

    run = enqueue(db, user)
    job = claim()
    token = context.bind(context.Execution(run.id, user.id, run.session_id, job["lease_token"]))
    try:
        scheduler_service.create_block(
            db, user, {"date": "2030-01-01", "start": "09:00", "end": "10:00", "label": "Old block"}
        )
        prepared = draft_service.prepare(
            db, user, [Action(kind="preset_apply", preset_id="student", clear_existing=True)]
        )
        draft = draft_service.stage(db, user, run.id, prepared)
        assert len(scheduler_service.user_blocks(db, user.id)) == 1
        result = draft_service.decide(db, user, draft.id, draft.revision, True)
        assert result["success"]
        assert len(scheduler_service.user_blocks(db, user.id)) == 3
        assert draft_service.decide(db, user, draft.id, draft.revision, True) == result
        assert len(scheduler_service.user_blocks(db, user.id)) == 3
    finally:
        context.unbind(token)


def test_evaluator_cannot_pass_a_blocking_issue(db, user, graph, monkeypatch):
    setup_model(monkeypatch)
    original = __import__("app.integrations.openrouter", fromlist=["generate"]).generate

    def generate(role, prompt, data, output_type, cache_key):
        if role == "evaluator":
            return Evaluation(
                candidate_revision=data["candidate_revision"],
                verdict="pass",
                issues=[
                    {
                        "id": "unsafe-pass",
                        "severity": "blocking",
                        "task_ids": ["plan"],
                        "evidence": "Missing request detail",
                        "required_fix": "Repair it",
                    }
                ],
                explanation="Conflicting verdict",
            )
        return original(role, prompt, data, output_type, cache_key)

    monkeypatch.setattr("app.integrations.openrouter.generate", generate)
    run = enqueue(db, user)
    run_once(graph)
    run = reload(db, run)
    assert run.status == "awaiting_input", run.error
    assert not db.exec(select(Draft)).all()


def test_checkpoint_serializer_is_strict(graph):
    assert graph.checkpointer.serde._allowed_msgpack_modules is None
    assert graph.checkpointer.serde.pickle_fallback is False
