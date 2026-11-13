"""Serializable state and idempotent worker-result reducer."""

from typing import Annotated, TypedDict


def merge_results(previous: dict, incoming: dict) -> dict:
    if "__reset__" in incoming:
        return {}
    result = dict(previous or {})
    for key, value in incoming.items():
        if key in result and result[key] != value:
            raise ValueError("Conflicting worker results for the same task revision")
        result[key] = value
    return result


class AgentState(TypedDict, total=False):
    _resume_key: str
    turn: str
    context: dict
    understanding: dict
    orders: list
    expected: dict
    results: Annotated[dict, merge_results]
    candidate: dict
    candidate_revision: str
    evaluation: dict
    issues: list
    rounds: int
    question: str
    question_reason: str
    route: str
    draft: dict
    result: dict
    seen_candidates: list
    seen_issues: list
    optimization_question: str
    assumptions: list


class WorkerState(TypedDict, total=False):
    order: dict
    key: str
    turn: str
    context: dict
    constraints: dict
    dependencies: dict
    feedback: list
    results: Annotated[dict, merge_results]
