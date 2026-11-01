"""Run with python -m app.runtime.worker. API processes never own durable jobs."""

import logging
import threading
import time
from datetime import timedelta

from langgraph.types import Command
from sqlmodel import Session, select

from app.agents.graph import build_graph
from app.core.config import GRAPH_VERSION, LEASE_SECONDS
from app.db.models import AgentRun, AgentSession, Draft, OperationOutcome, new_id, utc_now
from app.db.session import engine, verify_schema
from app.integrations.google_sync import sync_once
from app.runtime import context
from app.runtime.checkpoints import checkpoint_store

logger = logging.getLogger(__name__)


def claim():
    with Session(engine) as db:
        now = utc_now()
        run = db.exec(
            select(AgentRun)
            .where(
                (AgentRun.status == "queued")
                | ((AgentRun.status == "running") & (AgentRun.lease_until < now))
            )
            .order_by(AgentRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if run is None:
            return None
        run.lease_token, run.lease_until = new_id(), now + timedelta(seconds=LEASE_SECONDS)
        run.status, run.updated_at = "running", now
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.model_dump()


def heartbeat(job, stop):
    previous = time.monotonic()
    while not stop.wait(5):
        now = time.monotonic()
        with Session(engine) as db:
            run = db.exec(select(AgentRun).where(AgentRun.id == job["id"]).with_for_update()).one()
            if (
                run.lease_token != job["lease_token"]
                or run.status != "running"
                or run.lease_until <= utc_now()
            ):
                return
            run.active_seconds += now - previous
            run.lease_until = utc_now() + timedelta(seconds=LEASE_SECONDS)
            db.add(run)
            db.commit()
        previous = now


def execute(job, graph):
    identity = context.Execution(job["id"], job["user_id"], job["session_id"], job["lease_token"])
    token = context.bind(identity)
    stop = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(job, stop), daemon=True)
    thread.start()
    started = time.monotonic()
    status, result, pending, error = "failed", {}, {}, None
    try:
        if job["graph_version"] != GRAPH_VERSION:
            raise ValueError("This saved run uses an incompatible graph version. Start a new request.")
        config = {"configurable": {"thread_id": job["id"]}, "max_concurrency": 2, "recursion_limit": 100}
        state = graph.get_state(config)
        resume_id = job["input"].get("resume_request_id")
        if "resume" in job["input"] and state.values.get("_resume_key") != resume_id:
            graph_input = Command(resume=job["input"]["resume"])
        else:
            graph_input = None if state.values else {}
        output = graph.invoke(graph_input, config)
        interrupts = output.get("__interrupt__", ())
        if interrupts:
            item = interrupts[0]
            pending = {**item.value, "interrupt_id": item.id}
            status = "awaiting_approval" if item.value.get("kind") == "approval" else "awaiting_input"
        else:
            status, result = "completed", output.get("result", {})
    except context.LeaseLost:
        status = "cancelled"
    except Exception as exc:
        # Provider details, credentials, and raw responses never reach the browser.
        from app.integrations.openrouter import ModelUnavailable

        if isinstance(exc, (ValueError, context.BudgetExhausted, ModelUnavailable)):
            error = str(exc)[:1000]
        else:
            logger.exception("Run %s failed", job["id"])
            error = "The request could not complete. Progress is saved; retry or submit a narrower request."
    finally:
        stop.set()
        thread.join(timeout=10)
        context.unbind(token)
    with Session(engine) as db:
        run = db.exec(select(AgentRun).where(AgentRun.id == job["id"]).with_for_update()).one()
        if run.lease_token != job["lease_token"] or run.status != "running":
            return
        if run.cancel_requested:
            status = "cancelled"
        drafts = list(db.exec(select(Draft).where(Draft.run_id == run.id)).all())
        committed = next((draft for draft in drafts if draft.status == "confirmed"), None)
        if status in ("cancelled", "failed") and committed:
            saved = db.get(OperationOutcome, f"draft:{committed.id}:{committed.revision}")
            result = {
                **(saved.result if saved else {}),
                "response": "Execution stopped after calendar changes were saved. Those committed changes remain in your calendar.",
            }
        conversation = db.get(AgentSession, run.session_id)
        conversation.last_accessed_at = utc_now()
        finished = next(
            (draft for draft in reversed(drafts) if draft.status in ("confirmed", "rejected")), None
        )
        if finished:
            conversation.status = finished.status
            conversation.finished_at = utc_now()
        db.add(conversation)
        run.status, run.result, run.pending, run.error = status, result, pending, error
        run.stage = {
            "awaiting_input": "Awaiting your answer",
            "awaiting_approval": "Awaiting approval",
            "completed": "Completed",
            "failed": "Needs attention",
            "cancelled": "Cancelled",
        }[status]
        # Heartbeats accounted for all full intervals; include the remaining interval.
        elapsed = time.monotonic() - started
        run.active_seconds = max(run.active_seconds, job["active_seconds"] + elapsed)
        run.lease_token, run.lease_until, run.updated_at = None, None, utc_now()
        db.add(run)
        if status in ("failed", "cancelled"):
            for draft in db.exec(
                select(Draft).where(Draft.run_id == run.id, Draft.status == "pending")
            ).all():
                draft.status = status
                db.add(draft)
        db.commit()


def run_once(graph):
    job = claim()
    if not job:
        return False
    execute(job, graph)
    return True


def sync_loop(stop):
    while not stop.is_set():
        try:
            worked = sync_once()
        except Exception:
            logger.exception("Synchronization worker iteration failed")
            worked = False
        stop.wait(0.25 if worked else 2)


def main():
    logging.basicConfig(level=logging.INFO)
    verify_schema()
    stop = threading.Event()
    sync_thread = threading.Thread(target=sync_loop, args=(stop,), daemon=True)
    sync_thread.start()
    try:
        with checkpoint_store() as saver:
            graph = build_graph(saver)
            while True:
                try:
                    worked = run_once(graph)
                except Exception:
                    logger.exception("Worker iteration failed; expired leases will be reclaimed")
                    worked = False
                if not worked:
                    time.sleep(1)
    finally:
        stop.set()
        sync_thread.join(timeout=15)


if __name__ == "__main__":
    main()
