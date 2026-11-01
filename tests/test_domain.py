from datetime import datetime, timezone

import pytest

from app.domain.contracts import Constraints, TaskSpec, WorkOrder, validate_work_orders
from app.domain.intervals import merge, requested_minutes, subtract
from app.domain.placement import place
from app.domain.time import event_instants


def constraints(**extra):
    return Constraints.model_validate(
        {
            "start_date": "2030-01-01",
            "end_date": "2030-01-02",
            "total_minutes": 120,
            "session_minutes": 60,
            "availability": [{"date": "2030-01-01", "start": "10:00", "end": "12:00"}],
            **extra,
        }
    )


def test_interval_math_and_finite_input():
    assert merge([(10, 20), (20, 30), (40, 50)]) == [(10, 30), (40, 50)]
    assert subtract(0, 60, [(10, 20), (15, 30), (50, 80)]) == [(0, 10), (30, 50)]
    assert requested_minutes(1.1) == 66
    for value in [0, -1, float("inf"), float("nan")]:
        with pytest.raises(ValueError):
            requested_minutes(value)


def test_global_solver_respects_windows_order_and_total():
    tasks = [
        TaskSpec(id="first", title="Read", duration_minutes=60),
        TaskSpec(id="second", title="Practice", duration_minutes=60, after=["first"]),
    ]
    output = place(tasks, constraints(), [], "UTC", now=datetime(2029, 1, 1, tzinfo=timezone.utc))
    assert output["status"] in ("optimal", "feasible")
    assert [(b["start"], b["end"]) for b in output["placements"]] == [("10:00", "11:00"), ("11:00", "12:00")]
    assert output["placements"][0]["label"] == "Read"


def test_solver_finds_arrangement_greedy_order_would_miss():
    c = constraints(
        total_minutes=90,
        session_minutes=None,
        availability=[
            {"date": "2030-01-01", "start": "09:00", "end": "10:00"},
            {"date": "2030-01-01", "start": "11:00", "end": "11:30"},
        ],
    )
    tasks = [
        TaskSpec(id="short", title="Short", duration_minutes=30),
        TaskSpec(id="long", title="Long", duration_minutes=60),
    ]
    result = place(tasks, c, [], "UTC", now=datetime(2029, 1, 1, tzinfo=timezone.utc))
    assert result["status"] in ("optimal", "feasible")
    assert result["placements"][0]["task_id"] == "long"


def test_infeasible_and_invalid_contracts():
    c = constraints(availability=[{"date": "2030-01-01", "start": "10:00", "end": "11:00"}])
    tasks = [
        TaskSpec(id="a", title="A", duration_minutes=60),
        TaskSpec(id="b", title="B", duration_minutes=60),
    ]
    assert place(tasks, c, [], "UTC", now=datetime(2029, 1, 1, tzinfo=timezone.utc))["status"] == "infeasible"
    with pytest.raises(ValueError):
        place([tasks[0]], c, [], "UTC")
    with pytest.raises(ValueError):
        validate_work_orders(
            [WorkOrder(id="a", worker="planning", objective="A", dependencies=["b"], duration_budget=120)],
            120,
        )


def test_exact_day_count_and_busy_time():
    c = constraints(
        days_count=2,
        availability=[
            {"date": "2030-01-01", "start": "08:00", "end": "12:00"},
            {"date": "2030-01-02", "start": "14:00", "end": "16:00"},
        ],
    )
    tasks = [
        TaskSpec(id="a", title="A", duration_minutes=60),
        TaskSpec(id="b", title="B", duration_minutes=60),
    ]
    busy = [{"starts_at": "2030-01-01T08:00:00+00:00", "ends_at": "2030-01-01T10:00:00+00:00"}]
    result = place(tasks, c, busy, "UTC", now=datetime(2029, 1, 1, tzinfo=timezone.utc))
    assert len({p["date"] for p in result["placements"]}) == 2
    assert result["placements"][0]["start"] == "10:00"


def test_dst_and_midnight():
    first, last = event_instants("2030-01-01", "23:00", "24:00", "Asia/Kolkata")
    assert (last - first).total_seconds() == 3600
    assert first.utcoffset().total_seconds() == 0
    with pytest.raises(ValueError, match="does not exist"):
        event_instants("2026-03-08", "02:10", "03:30", "America/New_York")
    with pytest.raises(ValueError, match="ambiguous"):
        event_instants("2026-11-01", "01:15", "02:30", "America/New_York")


def test_idempotent_result_reducer_and_stale_versions():
    from app.agents.state import merge_results

    assert merge_results({"a:0": {"x": 1}}, {"a:0": {"x": 1}, "a:1": {"x": 2}}) == {
        "a:0": {"x": 1},
        "a:1": {"x": 2},
    }
    with pytest.raises(ValueError):
        merge_results({"a:0": {"x": 1}}, {"a:0": {"x": 2}})


def test_availability_counts_elapsed_time_across_dst():
    from app.domain.availability import allocate, find_gaps

    result = allocate([], "2026-03-08T01:00:00-05:00", 2, "America/New_York", max_days=1)
    assert result["fulfilled"]
    assert result["allocated"][0]["end"] == "04:00"
    assert result["allocated"][0]["duration"] == 2
    gaps = find_gaps([], "2030-01-01T10:00:00+00:00", "2030-01-01T11:00:00+00:00", "UTC")
    assert len(gaps) == 1 and gaps[0]["duration"] == 1
    bounded = allocate([], "2030-01-01T10:00:00+00:00", 2, "UTC", until="2030-01-01T11:00:00+00:00")
    assert not bounded["fulfilled"] and bounded["missing"] == 1


def test_slack_and_start_after_are_enforced():
    c = constraints(total_minutes=60, availability=[{"date": "2030-01-01", "start": "10:00", "end": "14:00"}])
    output = place(
        [TaskSpec(id="a", title="Study", duration_minutes=60)],
        c,
        [],
        "UTC",
        now=datetime(2029, 1, 1, tzinfo=timezone.utc),
        slack=0.2,
        start_after="2030-01-01T11:00:00+00:00",
    )
    assert output["placements"][0]["start"] == "11:00"
    assert output["placements"][0]["end"] == "12:12"


def test_fixed_event_ambiguity_is_not_left_to_the_model():
    from app.domain.ambiguity import missing_event_details

    assert missing_event_details("Meeting at 8 tomorrow", []) == [
        "AM or PM for the event time",
        "the event duration",
    ]
    assert not missing_event_details("Meeting at 8 tomorrow", ["PM, for 45 minutes"])
    assert not missing_event_details("Meeting at 8 tomorrow", ["8pm, for 45 minutes"])
    assert not missing_event_details("Meeting at 8 tomorrow", ["8 a.m., for 45 minutes"])
    assert not missing_event_details("Meeting at 20:00 tomorrow for 45 minutes", [])
