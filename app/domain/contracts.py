"""Validated contracts shared by graph nodes and calendar services."""

from datetime import date as CalendarDate
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(Contract):
    date: CalendarDate
    start: str
    end: str

    @model_validator(mode="after")
    def valid(self):
        from app.domain.time_utils import validate_time_range

        validate_time_range(self.start, self.end)
        return self


class Constraints(Contract):
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None
    total_minutes: int | None = Field(default=None, gt=0, le=86400)
    session_minutes: int | None = Field(default=None, gt=0, le=1440)
    days_count: int | None = Field(default=None, gt=0, le=60)
    availability: list[Window] = Field(default_factory=list, max_length=120)
    ordering: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid(self):
        if self.start_date and self.end_date:
            days = (self.end_date - self.start_date).days
            if not 0 <= days < 60:
                raise ValueError("Flexible plans need a date range of at most 60 days")
        return self


class TaskSpec(Contract):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    duration_minutes: int = Field(gt=0, le=1440)
    after: list[str] = Field(default_factory=list)
    allowed_dates: list[CalendarDate] = Field(default_factory=list)


class EventData(Contract):
    date: CalendarDate | None = None
    start: str
    end: str
    label: str = Field(default="Busy", min_length=1, max_length=240)
    color: str = "#397969"
    repeatDays: list[int] = Field(default_factory=list)

    @field_validator("repeatDays")
    @classmethod
    def weekdays(cls, value):
        if any(day not in range(7) for day in value):
            raise ValueError("Weekdays must be 0 through 6")
        return sorted(set(value))

    @model_validator(mode="after")
    def valid(self):
        from app.domain.time_utils import validate_time_range

        validate_time_range(self.start, self.end)
        if not self.date and not self.repeatDays:
            raise ValueError("Date or repeatDays required")
        return self


class Action(Contract):
    kind: Literal["create", "update", "delete", "preset_apply", "preset_remove", "preset_save"]
    event: EventData | None = None
    block_id: int | None = Field(default=None, gt=0)
    expected_revision: int | None = Field(default=None, gt=0)
    preset_id: str | None = None
    name: str | None = None
    clear_existing: bool = False

    @model_validator(mode="after")
    def valid(self):
        if self.kind in ("create", "update") and self.event is None:
            raise ValueError("Event details required")
        if self.kind in ("update", "delete") and (self.block_id is None or self.expected_revision is None):
            raise ValueError("Event ID and current revision required")
        if self.kind in ("preset_apply", "preset_remove") and not self.preset_id:
            raise ValueError("Preset ID required")
        if self.kind == "preset_save" and not self.name:
            raise ValueError("Preset name required")
        return self


class WorkOrder(Contract):
    id: str = Field(min_length=1, max_length=64)
    worker: Literal["planning", "action", "research", "conversation"]
    objective: str = Field(min_length=1, max_length=4000)
    dependencies: list[str] = Field(default_factory=list)
    duration_budget: int | None = Field(default=None, gt=0, le=86400)
    context_refs: list[str] = Field(default_factory=list)


class Understanding(Contract):
    summary: str = Field(default="", max_length=4000)
    intent: Literal["plan", "action", "availability", "research", "chat"]
    constraints: Constraints = Field(default_factory=Constraints)
    locked_fields: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    work_orders: list[WorkOrder] = Field(default_factory=list, max_length=6)
    memory_suggestions: list[str] = Field(default_factory=list, max_length=3)
    title: str = Field(default="Calendar conversation", max_length=80)
    availability_mode: Literal["free", "schedule"] = "free"
    availability_end: str | None = None
    availability_start: str | None = None
    availability_hours: float | None = Field(default=None, gt=0, le=1440, allow_inf_nan=False)


class Source(Contract):
    url: str
    title: str
    excerpt: str = Field(max_length=4000)


class WorkerOutput(Contract):
    tasks: list[TaskSpec] = Field(default_factory=list, max_length=120)
    actions: list[Action] = Field(default_factory=list, max_length=120)
    answer: str = Field(default="", max_length=16000)
    sources: list[Source] = Field(default_factory=list, max_length=9)


class Issue(Contract):
    id: str
    severity: Literal["blocking", "suggestion"]
    task_ids: list[str] = Field(default_factory=list)
    evidence: str
    required_fix: str


class Evaluation(Contract):
    candidate_revision: str
    verdict: Literal["pass", "revise", "clarify", "blocked"]
    issues: list[Issue] = Field(default_factory=list)
    explanation: str


class RepairPlan(Contract):
    repairs: list[WorkOrder] = Field(default_factory=list, max_length=6)
    question: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if not self.repairs and not self.question:
            raise ValueError("Repair tasks or a clarification question are required")
        return self


def validate_work_orders(orders: list[WorkOrder], total_minutes: int | None = None) -> None:
    ids = [o.id for o in orders]
    if not orders or len(ids) != len(set(ids)):
        raise ValueError("Work orders must be nonempty and have unique IDs")
    known = set(ids)
    done = set()
    for _ in orders:
        ready = {o.id for o in orders if set(o.dependencies) <= done}
        if ready <= done:
            break
        done |= ready
    if done != known:
        raise ValueError("Work orders contain a cycle or missing dependency")
    planners = [o for o in orders if o.worker == "planning"]
    if planners and (
        any(o.duration_budget is None for o in planners)
        or sum(o.duration_budget or 0 for o in planners) != total_minutes
    ):
        raise ValueError("Planning work-order budgets must equal the requested total")
