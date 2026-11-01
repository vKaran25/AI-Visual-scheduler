"""One global CP-SAT solve for all proposed tasks; never writes the calendar."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from app.domain.contracts import Constraints, TaskSpec
from app.domain.intervals import subtract
from app.domain.time import wall_instant


def place(
    tasks: list[TaskSpec],
    constraints: Constraints,
    busy: list[dict],
    zone: str,
    now: datetime | None = None,
    seconds: float = 10,
    slack: float = 0,
    start_after: str | None = None,
) -> dict:

    if not tasks or not constraints.availability or not constraints.start_date or not constraints.end_date:
        raise ValueError("Tasks, date range, and explicit availability are required")

    if len(tasks) > 120 or len({t.id for t in tasks}) != len(tasks):
        raise ValueError("At most 120 uniquely identified tasks are supported")

    if sum(t.duration_minutes for t in tasks) != constraints.total_minutes:
        raise ValueError("Generated task durations do not equal the requested total")

    if constraints.session_minutes and any(t.duration_minutes != constraints.session_minutes for t in tasks):
        raise ValueError("Generated tasks changed the requested session length")

    import math

    if not math.isfinite(slack) or not 0 <= slack <= 2:
        raise ValueError("Slack must be finite and between 0 and 2")

    durations = {t.id: math.ceil(t.duration_minutes * (1 + slack)) for t in tasks}

    known = {t.id for t in tasks}

    if any(set(t.after) - known or t.id in t.after for t in tasks):
        raise ValueError("Unknown or self-referencing task dependency")

    completed = set()

    for _ in tasks:
        completed |= {t.id for t in tasks if set(t.after) <= completed}

    if completed != known:
        raise ValueError("Generated tasks contain a dependency cycle")

    now = now or datetime.now(timezone.utc)

    if start_after:
        boundary = datetime.fromisoformat(start_after)

        if boundary.tzinfo is None:
            boundary = boundary.replace(tzinfo=ZoneInfo(zone))

        now = max(now, boundary.astimezone(timezone.utc))

    epoch = datetime.combine(constraints.start_date, datetime.min.time(), tzinfo=ZoneInfo(zone)).astimezone(
        timezone.utc
    )

    def minute(instant):
        return int((instant - epoch).total_seconds() // 60)

    lower_now = math_ceil_minutes(now, epoch)

    windows = []

    for w in constraints.availability:
        if constraints.start_date <= w.date <= constraints.end_date:
            first = max(minute(wall_instant(w.date.isoformat(), w.start, zone)), lower_now)

            last = minute(wall_instant(w.date.isoformat(), w.end, zone))

            occupied = [
                (
                    minute(datetime.fromisoformat(b["starts_at"])),
                    math_ceil_minutes(datetime.fromisoformat(b["ends_at"]), epoch),
                )
                for b in busy
            ]

            for start, end in subtract(first, last, occupied):
                windows.append((w.date, start, end))

    model = cp_model.CpModel()

    variables, intervals, day_choices = {}, [], {}

    for task in tasks:
        eligible = [
            (day, a, b)
            for day, a, b in windows
            if b - a >= durations[task.id] and (not task.allowed_dates or day in task.allowed_dates)
        ]

        if not eligible:
            return {
                "status": "infeasible",
                "placements": [],
                "reason": f"No available contiguous interval for {task.title}",
            }

        start = model.new_int_var_from_domain(
            cp_model.Domain.from_intervals([[a, b - durations[task.id]] for _, a, b in eligible]),
            f"start_{task.id}",
        )

        end = model.new_int_var(0, max(b for _, _, b in windows), f"end_{task.id}")

        intervals.append(model.new_interval_var(start, durations[task.id], end, task.id))

        variables[task.id] = (start, end)

        choices = []

        for index, (day, a, b) in enumerate(eligible):
            chosen = model.new_bool_var(f"{task.id}_window_{index}")

            model.add(start >= a).only_enforce_if(chosen)

            model.add(end <= b).only_enforce_if(chosen)

            choices.append(chosen)

            day_choices.setdefault(day, []).append(chosen)

        model.add_exactly_one(choices)

    model.add_no_overlap(intervals)

    for task in tasks:
        for prior in task.after:
            model.add(variables[task.id][0] >= variables[prior][1])

    for prior, following in zip(constraints.ordering, constraints.ordering[1:]):
        if prior not in variables or following not in variables:
            raise ValueError("Ordering references an unknown task")

        model.add(variables[following][0] >= variables[prior][1])

    if constraints.days_count:
        used = []

        for day, choices in day_choices.items():
            flag = model.new_bool_var(f"used_{day}")

            model.add_max_equality(flag, choices)

            used.append(flag)

        model.add(sum(used) == constraints.days_count)

    model.minimize(sum(start for start, _ in variables.values()))

    solver = cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = seconds

    solver.parameters.num_search_workers = 1

    solver.parameters.random_seed = 0

    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "infeasible" if status == cp_model.INFEASIBLE else "unknown",
            "placements": [],
            "reason": "Constraints cannot all be met"
            if status == cp_model.INFEASIBLE
            else "Search limit reached; no infeasibility was proved",
        }

    placements = []

    for task in tasks:
        start, end = variables[task.id]

        first = (epoch + timedelta(minutes=solver.value(start))).astimezone(ZoneInfo(zone))

        last = (epoch + timedelta(minutes=solver.value(end))).astimezone(ZoneInfo(zone))

        placements.append(
            {
                "task_id": task.id,
                "date": first.date().isoformat(),
                "start": first.strftime("%H:%M"),
                "end": "24:00" if last.date() > first.date() else last.strftime("%H:%M"),
                "label": task.title
                + (f" · {durations[task.id] - task.duration_minutes}m buffer" if slack else ""),
                "repeatDays": [],
                "color": "#7c6aff",
            }
        )

    return {
        "status": "optimal" if status == cp_model.OPTIMAL else "feasible",
        "placements": sorted(placements, key=lambda b: (b["date"], b["start"])),
        "reason": "",
    }


def math_ceil_minutes(now, epoch):

    import math

    return math.ceil((now.astimezone(timezone.utc) - epoch).total_seconds() / 60)
