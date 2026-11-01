import time

import pytest


def test_paid_or_incapable_models_are_refused(monkeypatch):
    from app.integrations import openrouter

    monkeypatch.setattr(openrouter, "_catalog_at", time.monotonic())
    monkeypatch.setattr(
        openrouter,
        "_catalog",
        {
            "safe:free": {
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["response_format", "structured_outputs"],
            },
            "paid:free": {
                "pricing": {"prompt": "0", "completion": "0", "request": "0.1"},
                "supported_parameters": ["response_format", "structured_outputs"],
            },
            "weak:free": {"pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": []},
        },
    )
    openrouter.verify_free("safe:free")
    for name in ["normal-paid", "paid:free", "weak:free", "missing:free"]:
        with pytest.raises(openrouter.ModelUnavailable):
            openrouter.verify_free(name)


def test_research_rejects_private_and_insecure_destinations(monkeypatch):
    from app.integrations import research

    monkeypatch.setattr(research.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        research.public_addresses("example.com")
    with pytest.raises(ValueError):
        research.fetch_text("http://example.com")
    with pytest.raises(ValueError):
        research.fetch_text("https://example.com:8443")
    with pytest.raises(ValueError):
        research.fetch_text("https://user:password@example.com")


def test_durable_model_budget(db, user):
    from app.runtime import context
    from app.runtime.worker import claim
    from app.schemas.agent import AgentChatRequest
    from app.services.run_service import enqueue

    run = enqueue(db, user, AgentChatRequest(prompt="Test", request_id="budget"))
    job = claim()
    token = context.bind(context.Execution(run.id, user.id, run.session_id, job["lease_token"]))
    try:
        for _ in range(16):
            context.reserve_attempt()
        with pytest.raises(context.BudgetExhausted):
            context.reserve_attempt()
    finally:
        context.unbind(token)
    db.refresh(run)
    assert run.model_attempts == 16


def test_labeled_metrics_and_offline_runner():
    from app.evaluations.__main__ import metrics, offline

    result = offline()
    assert result["placed_minutes"] == 60 and result["requested_1_1_hours_minutes"] == 66
    assert metrics([{"accepted": True, "expected_accept": False}])["unsafe_acceptances"] == 1


def test_suggested_memory_is_deduplicated_and_needs_consent(db, user):
    from sqlmodel import select

    from app.agents.context import remember_understanding
    from app.db.models import Memory, MemoryProposal
    from app.domain.contracts import Understanding
    from app.runtime import context
    from app.runtime.worker import claim
    from app.schemas.agent import AgentChatRequest
    from app.services.run_service import enqueue

    run = enqueue(db, user, AgentChatRequest(prompt="Remember mornings", request_id="memory"))
    job = claim()
    token = context.bind(context.Execution(run.id, user.id, run.session_id, job["lease_token"]))
    try:
        understood = Understanding(intent="chat", memory_suggestions=["Prefer morning study"])
        remember_understanding(understood, "turn-1")
        remember_understanding(understood, "turn-2")
        assert len(db.exec(select(MemoryProposal)).all()) == 1
        assert not db.exec(select(Memory)).all()
    finally:
        context.unbind(token)
