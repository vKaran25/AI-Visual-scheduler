"""Combined orchestrator-worker and evaluator-optimizer LangGraph."""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from sqlmodel import Session

from app.agents import prompts
from app.agents.context import busy_instants, message, remember_understanding, snapshot
from app.agents.state import AgentState, WorkerState
from app.core.config import MAX_OPTIMIZATION_ROUNDS
from app.db.models import Draft, GoogleConnection, User, new_id
from app.db.session import engine
from app.domain.contracts import (
    Action,
    Constraints,
    Evaluation,
    RepairPlan,
    Source,
    Understanding,
    WorkerOutput,
    WorkOrder,
    validate_work_orders,
)
from app.domain.placement import place
from app.integrations import openrouter, research
from app.integrations.google_sync import refresh_for_dates
from app.runtime import context as execution
from app.services import draft_service, scheduler_service


def load_context(state):
    execution.event("Understanding")
    with Session(engine) as db:
        run = execution.fence(db)
        payload = dict(run.input)
    return {
        "turn": payload["turn"],
        "context": {
            **snapshot(),
            "request": payload["prompt"],
            "start_after": payload.get("start_after"),
            "slack": payload.get("slack", 0),
        },
        "results": {"__reset__": True},
        "orders": [],
        "expected": {},
        "rounds": 0,
        "candidate": {},
        "evaluation": {},
        "issues": [],
        "seen_candidates": [],
        "seen_issues": [],
        "result": {},
    }


def orchestrate(state):
    execution.event("Understanding")
    understood = openrouter.generate(
        "orchestrator",
        prompts.ORCHESTRATOR,
        {"context": state["context"], "previous_understanding": state.get("understanding", {})},
        Understanding,
        f"{state['turn']}:understanding",
    )
    remember_understanding(understood, state["turn"])
    return {
        "understanding": understood.model_dump(mode="json"),
        "orders": [o.model_dump(mode="json") for o in understood.work_orders],
        "expected": {o.id: 0 for o in understood.work_orders},
        "rounds": 0,
        "results": {"__reset__": True},
        "seen_candidates": [],
        "seen_issues": [],
    }


def validate_requirements(state):
    understood = Understanding.model_validate(state["understanding"])
    missing = list(understood.missing)
    if understood.intent in ("plan", "action", "availability") and not state["context"]["timezone_confirmed"]:
        missing.append("Confirm your calendar timezone using the timezone button, then reply to continue.")
    if understood.intent == "plan":
        c = understood.constraints
        for value, label in (
            (c.start_date, "start date"),
            (c.end_date, "deadline"),
            (c.total_minutes, "total study time"),
            (c.session_minutes, "session duration"),
            (c.availability, "available dates and daily hours"),
        ):
            if not value:
                missing.append(label)
    if missing:
        return {
            "route": "clarify",
            "question": "Please provide or confirm: " + "; ".join(dict.fromkeys(missing)),
            "question_reason": "missing",
        }
    if understood.intent == "availability":
        if not understood.availability_start or (
            understood.availability_mode == "free"
            and not understood.availability_hours
            and not understood.availability_end
        ):
            return {
                "route": "clarify",
                "question": "When should I search from, and how much free time do you need?",
                "question_reason": "missing",
            }
        return {"route": "availability"}
    try:
        validate_work_orders(understood.work_orders, understood.constraints.total_minutes)
    except ValueError as exc:
        return {
            "route": "optimize",
            "issues": [
                {
                    "id": "work-orders",
                    "severity": "blocking",
                    "task_ids": [],
                    "evidence": str(exc),
                    "required_fix": "Repair the work-order DAG and duration budgets without changing user constraints",
                }
            ],
        }
    return {"route": "dispatch"}


def clarify(state):
    question = state.get("question") or "What would you like to change so I can complete this request?"
    message(f"{execution.current().run_id}:{state['turn']}:question", question)
    answer = interrupt({"kind": "question", "question": question})
    # This node restarts on resume; the message key prevents duplicate messages.
    if not isinstance(answer, dict) or not answer.get("answer"):
        raise ValueError("A clarification answer is required")
    fresh = snapshot()
    with Session(engine) as db:
        resume_key = execution.fence(db).input.get("resume_request_id", "")
    return {
        "_resume_key": resume_key,
        "turn": new_id(),
        "context": {
            **fresh,
            "request": state["context"]["request"],
            "follow_up": answer["answer"],
            "start_after": state["context"].get("start_after"),
            "slack": state["context"].get("slack", 0),
        },
        "rounds": 0,
    }


def dispatch(state):
    execution.event("Planning" if state["understanding"]["intent"] == "plan" else "Preparing proposal")
    return {}


def ready_workers(state):
    ready = []
    for order in state["orders"]:
        key = f"{order['id']}:{state['expected'][order['id']]}"
        if key in state["results"]:
            continue
        dependencies = {
            dep: state["results"].get(f"{dep}:{state['expected'][dep]}") for dep in order["dependencies"]
        }
        if all(dependencies.values()):
            ready.append(
                Send(
                    "specialist",
                    {
                        "order": order,
                        "key": key,
                        "turn": state["turn"],
                        "context": scoped_context(state["context"], order),
                        "constraints": state["understanding"]["constraints"],
                        "dependencies": dependencies,
                        "feedback": state.get("issues", []),
                    },
                )
            )
    if ready:
        return ready
    if len(state["orders"]) == sum(
        f"{o['id']}:{state['expected'][o['id']]}" in state["results"] for o in state["orders"]
    ):
        return "validate_candidate"
    raise ValueError("No ready workers; invalid dependency graph")


def scoped_context(source, order):
    keys = {
        "planning": ("request", "follow_up", "answers", "now", "timezone", "preferences"),
        "action": ("request", "follow_up", "answers", "now", "timezone", "calendar", "presets"),
        "research": ("request", "follow_up", "answers", "now"),
        "conversation": ("request", "follow_up", "answers", "now", "timezone", "calendar", "summary"),
    }
    return {key: source[key] for key in keys[order["worker"]] if key in source}


def specialist(state):
    order = WorkOrder.model_validate(state["order"])
    cache_key = f"{state['turn']}:worker:{state['key']}"
    prior = execution.artifact(cache_key)
    if prior:
        return {"results": {state["key"]: prior}}
    data = {
        "assignment": order.model_dump(mode="json"),
        "constraints": state["constraints"],
        "context": state["context"],
        "dependencies": state["dependencies"],
        "feedback": state["feedback"],
    }
    if order.worker == "research":
        execution.event("Researching", task_id=order.id)
        evidence_key = cache_key + ":evidence"
        evidence = execution.artifact(evidence_key)
        if evidence is None:
            evidence = research.research([order.objective])
            execution.save_artifact(evidence_key, "research", evidence)
        output = openrouter.generate(
            "conversation",
            prompts.WORKERS["conversation"],
            {"objective": order.objective, "evidence": evidence},
            WorkerOutput,
            cache_key + ":model",
        )
        trusted = {s["url"]: s for s in evidence["sources"]}
        output.sources = [Source.model_validate(v) for v in trusted.values()]
        if not trusted:
            output.answer = (
                "External research was unavailable. I can continue with the information you provide."
            )
    else:
        output = openrouter.generate(
            order.worker, prompts.WORKERS[order.worker], data, WorkerOutput, cache_key + ":model"
        )
    if order.worker != "planning" and output.tasks:
        raise ValueError("Only planning workers can produce study tasks")
    if order.worker != "action" and output.actions:
        raise ValueError("Only action workers can produce calendar operations")
    if order.worker == "planning" and sum(t.duration_minutes for t in output.tasks) != order.duration_budget:
        # Keep the result for the coded validator and targeted optimizer.
        pass
    result = {"work_id": order.id, "revision": state["key"], "output": output.model_dump(mode="json")}
    execution.save_artifact(cache_key, "worker_result", result)
    return {"results": {state["key"]: result}}


def collect(state):
    return {}


def validate_candidate(state):
    execution.event("Checking")
    outputs = {
        o["id"]: WorkerOutput.model_validate(
            state["results"][f"{o['id']}:{state['expected'][o['id']]}"]["output"]
        )
        for o in state["orders"]
    }
    tasks, actions, answers, sources = [], [], [], []
    for order in state["orders"]:
        output = outputs[order["id"]]
        if (
            order["worker"] == "planning"
            and sum(t.duration_minutes for t in output.tasks) != order["duration_budget"]
        ):
            return {
                "route": "optimize",
                "issues": [
                    {
                        "id": "duration-budget",
                        "severity": "blocking",
                        "task_ids": [order["id"]],
                        "evidence": "Worker durations do not match its assigned minutes",
                        "required_fix": "Return tasks totaling the exact assigned duration budget",
                    }
                ],
            }
        tasks.extend(output.tasks)
        actions.extend(output.actions)
        if output.answer:
            answers.append(output.answer)
        sources.extend(s.model_dump() for s in output.sources)
    if state["understanding"]["intent"] == "action" and any(a.kind == "create" for a in actions):
        from app.domain.ambiguity import missing_event_details

        missing = missing_event_details(state["context"]["request"], state["context"].get("answers", []))
        if missing:
            return {
                "route": "clarify",
                "question": "Please confirm " + " and ".join(missing) + ".",
                "question_reason": "ambiguous-event",
            }
    constraints = Constraints.model_validate(state["understanding"]["constraints"])
    with Session(engine, expire_on_commit=False) as db:
        execution.fence(db)
        user = db.get(User, execution.current().user_id)
        db.commit()
        if tasks:
            if db.get(GoogleConnection, user.id) and not refresh_for_dates(
                db, user, [constraints.start_date.isoformat(), constraints.end_date.isoformat()]
            ):
                return {
                    "route": "clarify",
                    "question": "Google availability could not be refreshed. Reconnect Google or ask me to retry.",
                    "question_reason": "availability",
                }
            try:
                solved = place(
                    tasks,
                    constraints,
                    busy_instants(db, user, constraints),
                    user.timezone,
                    slack=state["context"].get("slack", 0),
                    start_after=state["context"].get("start_after"),
                )
            except ValueError as exc:
                return {
                    "route": "optimize",
                    "issues": [
                        {
                            "id": "task-contract",
                            "severity": "blocking",
                            "task_ids": [o["id"] for o in state["orders"] if o["worker"] == "planning"],
                            "evidence": str(exc),
                            "required_fix": "Repair generated tasks while preserving every explicit constraint",
                        }
                    ],
                }
            if solved["status"] not in ("feasible", "optimal"):
                return {
                    "route": "clarify",
                    "question": solved["reason"]
                    + ". Would you like to change available hours or dates, or retry without changing them?",
                    "question_reason": solved["status"],
                }
            actions.extend(
                Action(kind="create", event={k: v for k, v in event.items() if k != "task_id"})
                for event in solved["placements"]
            )
        try:
            prepared = (
                draft_service.prepare(db, user, actions)
                if actions
                else {"operations": [], "preview": {}, "hash": draft_service.digest(answers)}
            )
        except ValueError as exc:
            return {
                "route": "clarify",
                "question": str(exc) + ". Which event or time should I change?",
                "question_reason": "conflict",
            }
    candidate = {
        "actions": [a.model_dump(mode="json") for a in actions],
        "prepared": prepared,
        "answer": "\n\n".join(answers),
        "sources": sources,
    }
    revision = draft_service.digest(candidate)
    if revision in state.get("seen_candidates", []):
        return {
            "route": "clarify",
            "question": "The repair did not change the proposal. Please narrow the request or specify the change you want.",
            "question_reason": "no-progress",
        }
    execution.save_artifact(f"{state['turn']}:candidate:{revision}", "candidate", candidate)
    needs_evaluation = (
        state["understanding"]["intent"] in ("plan", "research") or len(actions) > 1 or bool(sources)
    )
    return {
        "candidate": candidate,
        "candidate_revision": revision,
        "route": "evaluate" if needs_evaluation else "present",
        "seen_candidates": state.get("seen_candidates", []) + [revision],
    }


def audited_validation(state):
    result = validate_candidate(state)
    execution.save_artifact(
        f"{state['turn']}:validation:{state.get('rounds', 0)}",
        "validation_report",
        {
            "status": "passed" if result["route"] in ("evaluate", "present") else "blocked",
            "issues": result.get("issues", []),
            "reason": result.get("question_reason"),
            "candidate_revision": result.get("candidate_revision"),
        },
    )
    return result


def evaluate(state):
    execution.event("Checking quality")
    report = openrouter.generate(
        "evaluator",
        prompts.EVALUATOR,
        {
            "candidate_revision": state["candidate_revision"],
            "request": state["context"],
            "understanding": state["understanding"],
            "candidate": state["candidate"],
        },
        Evaluation,
        f"{state['turn']}:evaluation:{state['candidate_revision']}",
    )
    if report.candidate_revision != state["candidate_revision"]:
        raise ValueError("Evaluator returned a stale candidate revision")
    blocking = any(issue.severity == "blocking" for issue in report.issues)
    verdict = report.verdict
    if verdict == "pass" and blocking:
        verdict = "revise"
    route = {"pass": "present", "revise": "optimize", "clarify": "clarify", "blocked": "clarify"}[verdict]
    return {
        "evaluation": report.model_dump(mode="json"),
        "issues": [i.model_dump() for i in report.issues],
        "question": report.explanation,
        "question_reason": "evaluation",
        "route": route,
    }


def optimize(state):
    execution.event("Improving")
    issue_hash = draft_service.digest(state.get("issues", []))
    if state.get("rounds", 0) >= MAX_OPTIMIZATION_ROUNDS or issue_hash in state.get("seen_issues", []):
        return {
            "route": "clarify",
            "question": "I could not resolve the remaining checks within the repair limit. Please narrow the goal or tell me what to change.",
            "question_reason": "repair-limit",
        }
    repair = openrouter.generate(
        "optimizer",
        prompts.OPTIMIZER,
        {
            "orders": state["orders"],
            "constraints": state["understanding"]["constraints"],
            "issues": state.get("issues", []),
            "candidate": state.get("candidate", {}),
        },
        RepairPlan,
        f"{state['turn']}:repair:{state.get('rounds', 0)}",
    )
    if repair.question:
        return {"route": "clarify", "question": repair.question, "question_reason": "optimizer"}
    existing = {o["id"]: o for o in state["orders"]}
    replacements = {o.id: o.model_dump(mode="json") for o in repair.repairs}
    if set(replacements) - set(existing):
        raise ValueError("Optimizer cannot introduce unassigned worker IDs")
    for key, order in replacements.items():
        if order["worker"] != existing[key]["worker"] or (
            state.get("candidate") and order["duration_budget"] != existing[key]["duration_budget"]
        ):
            raise ValueError("Optimizer cannot change worker identity or assigned duration budgets")
    orders = [replacements.get(o["id"], o) for o in state["orders"]]
    validate_work_orders(
        [WorkOrder.model_validate(o) for o in orders], state["understanding"]["constraints"]["total_minutes"]
    )
    invalidated = set(replacements)
    for _ in orders:
        invalidated |= {o["id"] for o in orders if set(o["dependencies"]) & invalidated}
    expected = {key: value + (1 if key in invalidated else 0) for key, value in state["expected"].items()}
    return {
        "orders": orders,
        "expected": expected,
        "rounds": state.get("rounds", 0) + 1,
        "seen_issues": state.get("seen_issues", []) + [issue_hash],
        "route": "dispatch",
    }


def availability(state):
    from datetime import datetime, timedelta

    understood = Understanding.model_validate(state["understanding"])
    with Session(engine) as db:
        execution.fence(db)
        user = db.get(User, execution.current().user_id)
        if db.get(GoogleConnection, user.id):
            dates = [datetime.fromisoformat(understood.availability_start).date().isoformat()]
            dates.append(
                datetime.fromisoformat(understood.availability_end).date().isoformat()
                if understood.availability_end
                else (
                    datetime.fromisoformat(understood.availability_start).date() + timedelta(days=60)
                ).isoformat()
            )
            db.commit()
            if not refresh_for_dates(db, user, dates):
                return {
                    "result": {
                        "response": "Google availability could not be refreshed; please reconnect or retry before relying on these times."
                    }
                }

        if understood.availability_mode == "schedule":
            first = datetime.fromisoformat(understood.availability_start).date()
            last = (
                datetime.fromisoformat(understood.availability_end).date()
                if understood.availability_end
                else first
            )
            if not 0 <= (last - first).days <= 41:
                return {"result": {"response": "Please choose a calendar range of at most 42 days."}}
            rows = []
            for offset in range((last - first).days + 1):
                rows.extend(
                    scheduler_service.slots_for_date(db, user, (first + timedelta(days=offset)).isoformat())
                )
            response = "\n".join(f"{b['date']} {b['start']}–{b['end']} {b['label']}" for b in rows)
            return {
                "result": {"response": response or "No confirmed events in that range.", "schedule": rows}
            }
        if not understood.availability_hours:
            from app.domain.availability import find_gaps

            blocks = [
                {**scheduler_service.block_to_dict(b), "starts_at": b.starts_at, "ends_at": b.ends_at}
                for b in scheduler_service.user_blocks(db, user.id)
            ]
            result = {
                "allocated": find_gaps(
                    blocks, understood.availability_start, understood.availability_end, user.timezone
                ),
                "fulfilled": True,
            }
        else:
            result = scheduler_service.compute_free_blocks(
                db,
                user,
                understood.availability_start,
                understood.availability_hours,
                end_dt_str=understood.availability_end,
            )
    response = "\n".join(f"{b['date']} {b['start']}–{b['end']}" for b in result["allocated"])
    if not result["fulfilled"]:
        response += f"\nMissing {result['missing']:.2f} hours within the search horizon."
    return {"result": {"response": response or "No matching free time was found.", "availability": result}}


def present(state):
    candidate = state["candidate"]
    if not candidate["prepared"]["operations"]:
        return {
            "route": "finish",
            "result": {"response": candidate["answer"], "sources": candidate["sources"]},
        }
    with Session(engine, expire_on_commit=False) as db:
        execution.fence(db)
        user = db.get(User, execution.current().user_id)
        draft = draft_service.stage(db, user, execution.current().run_id, candidate["prepared"])
        return {
            "route": "approval",
            "draft": {"id": draft.id, "revision": draft.revision, "preview": draft.preview},
        }


def approval(state):
    draft = state["draft"]
    summary = "Review the proposed calendar changes. They will be saved only after you approve."
    message(f"{execution.current().run_id}:preview:{draft['revision']}", summary)
    decision = interrupt(
        {
            "kind": "approval",
            "question": summary,
            "draft_id": draft["id"],
            "revision": draft["revision"],
            "preview": draft["preview"],
        }
    )
    with Session(engine) as db:
        resume_key = execution.fence(db).input.get("resume_request_id", "")
    if isinstance(decision, dict) and decision.get("answer"):
        with Session(engine) as db:
            execution.fence(db)
            row = db.get(Draft, draft["id"])
            row.status = "superseded"
            db.add(row)
            db.commit()
        return {
            "_resume_key": resume_key,
            "route": "orchestrate",
            "turn": new_id(),
            "context": {
                **snapshot(),
                "request": state["context"]["request"],
                "follow_up": decision["answer"],
                "slack": state["context"].get("slack", 0),
                "start_after": state["context"].get("start_after"),
            },
        }
    if (
        not isinstance(decision, dict)
        or decision.get("draft_id") != draft["id"]
        or decision.get("revision") != draft["revision"]
        or decision.get("decision") not in ("accept", "reject")
    ):
        raise ValueError("Approval must match the current draft revision")
    try:
        with Session(engine, expire_on_commit=False) as db:
            execution.fence(db)
            user = db.get(User, execution.current().user_id)
            db.commit()
            if decision["decision"] == "accept" and db.get(GoogleConnection, user.id):
                if not refresh_for_dates(
                    db,
                    user,
                    [
                        op["event"]["date"]
                        for op in draft["preview"]["changes"]
                        if op.get("event", {}).get("date")
                    ],
                ):
                    return {
                        "_resume_key": resume_key,
                        "route": "clarify",
                        "question": "Google refresh failed. Please reconnect or ask to retry.",
                        "question_reason": "availability",
                    }
            result = draft_service.decide(
                db, user, draft["id"], draft["revision"], decision["decision"] == "accept"
            )
        return {"_resume_key": resume_key, "route": "finish", "result": result}
    except ValueError as exc:
        with Session(engine) as db:
            execution.fence(db)
            stale = db.get(Draft, draft["id"])
            if stale.status == "pending":
                stale.status = "superseded"
                db.add(stale)
                db.commit()
        return {
            "_resume_key": resume_key,
            "route": "clarify",
            "question": str(exc) + ". Please tell me how to revise the proposal.",
            "question_reason": "stale",
        }


def finish(state):
    result = state.get("result", {})
    message(
        f"{execution.current().run_id}:{state['turn']}:final", result.get("response", "Request completed.")
    )
    return {}


def build_graph(checkpointer):
    worker = StateGraph(WorkerState)
    worker.add_node("execute_assignment", specialist)
    worker.add_edge(START, "execute_assignment")
    worker.add_edge("execute_assignment", END)
    worker_graph = worker.compile()
    graph = StateGraph(AgentState)
    for name, node in [
        ("load_context", load_context),
        ("orchestrate", orchestrate),
        ("validate_requirements", validate_requirements),
        ("clarify", clarify),
        ("dispatch", dispatch),
        ("specialist", worker_graph),
        ("collect", collect),
        ("validate_candidate", audited_validation),
        ("evaluate", evaluate),
        ("optimize", optimize),
        ("availability", availability),
        ("present", present),
        ("approval", approval),
        ("finish", finish),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "orchestrate")
    graph.add_edge("orchestrate", "validate_requirements")
    graph.add_conditional_edges(
        "validate_requirements", lambda s: s["route"], ["clarify", "dispatch", "availability", "optimize"]
    )
    graph.add_edge("clarify", "orchestrate")
    graph.add_conditional_edges("dispatch", ready_workers, ["specialist", "validate_candidate"])
    graph.add_edge("specialist", "collect")
    graph.add_edge("collect", "dispatch")
    graph.add_conditional_edges(
        "validate_candidate", lambda s: s["route"], ["clarify", "evaluate", "present", "optimize"]
    )
    graph.add_conditional_edges("evaluate", lambda s: s["route"], ["present", "optimize", "clarify"])
    graph.add_conditional_edges("optimize", lambda s: s["route"], ["dispatch", "clarify"])
    graph.add_conditional_edges("present", lambda s: s["route"], ["approval", "finish"])
    graph.add_conditional_edges("approval", lambda s: s["route"], ["orchestrate", "clarify", "finish"])
    graph.add_edge("availability", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
