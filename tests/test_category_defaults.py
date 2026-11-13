"""Simple requests get sensible defaults instead of follow-up questions."""

import pytest
from sqlmodel import select

from app.agents.graph import apply_defaults
from app.db.models import AgentRun, Draft
from app.domain.ambiguity import has_duration, missing_event_details
from app.domain.categories import classify, plus_minutes
from app.domain.contracts import Understanding, WorkerOutput, WorkOrder
from app.runtime.worker import run_once
from app.schemas.agent import AgentChatRequest
from app.services import run_service


@pytest.mark.parametrize(
    "text,name,minutes",
    [
        ("review of project", "Meeting", 60),
        ("Physics lecture", "Class", 60),
        ("chemistry lab", "Lab", 120),
        ("gym", "Exercise", 60),
        ("lunch with Riya", "Meal", 45),
        ("call mom", "Call", 30),
        ("revise calculus", "Study", 60),
        ("maths exam", "Exam", 120),
        ("something else entirely", "Event", 60),
    ],
)
def test_events_are_classified_into_student_categories(text, name, minutes):
    category = classify(text)
    assert (category.name, category.minutes) == (name, minutes)


def test_lengths_never_cross_midnight():
    assert plus_minutes("09:00", 60) == "10:00"
    assert plus_minutes("23:30", 60) == "24:00"


def test_missing_length_is_not_a_question_but_missing_am_pm_still_is():
    assert missing_event_details("Schedule 9 am review of project", []) == []
    assert not has_duration("Schedule 9 am review of project")
    assert has_duration("study from 4 to 6") and has_duration("gym for 45 minutes")
    assert missing_event_details("Schedule review at 9", []) == ["AM or PM for the event time"]


def test_plan_without_dates_session_or_hours_gets_defaults():
    understood = Understanding(
        intent="plan",
        constraints={"total_minutes": 240},
        missing=["start date", "session length", "available dates and daily hours"],
    )
    filled, notes, orders = apply_defaults(
        understood, {"now": "2030-01-07T12:00:00+05:30", "request": "Plan 4h"}
    )
    c = filled.constraints
    assert filled.missing == []
    assert (str(c.start_date), str(c.end_date), c.session_minutes) == ("2030-01-07", "2030-01-13", 60)
    assert len(c.availability) == 7 and c.availability[0].start == "08:00"
    assert orders[0].worker == "planning" and orders[0].duration_budget == 240
    assert any("8 AM and 9 PM" in note for note in notes)


def test_genuinely_missing_details_are_still_asked():
    understood = Understanding(
        intent="plan", constraints={"total_minutes": 60}, missing=["which subject to study"]
    )
    filled, _, _ = apply_defaults(understood, {"now": "2030-01-07T12:00:00+05:30", "request": "Plan"})
    assert filled.missing == ["which subject to study"]


def test_simple_event_request_goes_straight_to_a_draft_with_a_default_length(db, user, graph, monkeypatch):
    def generate(role, prompt, data, output_type, cache_key):
        if role == "orchestrator":
            # Free models often (wrongly) list the length and date as missing; they must not cause a question.
            return Understanding(intent="action", missing=["duration", "date"], work_orders=[])
        if role == "action":
            event = {"date": "2030-01-07", "start": "09:00", "end": "09:15", "label": "Project review"}
            return WorkerOutput(actions=[{"kind": "create", "event": event}])
        raise AssertionError(role)

    monkeypatch.setattr("app.integrations.openrouter.generate", generate)
    run = run_service.enqueue(
        db, user, AgentChatRequest(prompt="schedule 9 am review of project", request_id="category-default")
    )
    assert run_once(graph)
    db.expire_all()
    run = db.get(AgentRun, run.id)
    assert run.status == "awaiting_approval", run.error
    draft = db.exec(select(Draft).where(Draft.run_id == run.id, Draft.status == "pending")).one()
    event = draft.preview["scheduled"][0]
    assert (event["start"], event["end"]) == ("09:00", "10:00")
    assert any("Length assumed: 1h" in note for note in draft.preview["notes"])


def test_work_order_is_created_when_the_model_forgets_it():
    understood = Understanding(intent="action", missing=["date"])
    filled, _, orders = apply_defaults(
        understood, {"now": "2030-01-07T08:00:00+05:30", "request": "gym at 6 pm"}
    )
    assert filled.missing == [] and [o.worker for o in orders] == ["action"]
    assert isinstance(filled.work_orders[0], WorkOrder)


@pytest.mark.parametrize(
    "request_text", ["schedule 9 am review of project", "gym at 7pm", "project review at 9:30"]
)
def test_a_clock_time_means_one_event_even_if_the_model_says_plan(request_text):
    understood = Understanding(intent="plan", constraints={"total_minutes": 60})
    filled, _, orders = apply_defaults(
        understood, {"now": "2030-01-07T08:00:00+05:30", "request": request_text}
    )
    assert filled.intent == "action" and [o.worker for o in orders] == ["action"]


def test_real_study_plans_stay_plans_even_with_times():
    request_text = "Plan 4 hours of calculus revision between 3 pm and 8 pm this week"
    understood = Understanding(intent="plan", constraints={"total_minutes": 240})
    filled, _, _ = apply_defaults(understood, {"now": "2030-01-07T08:00:00+05:30", "request": request_text})
    assert filled.intent == "plan"
