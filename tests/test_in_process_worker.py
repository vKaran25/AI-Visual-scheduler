"""The worker loop can run inside the web process (single-service deployments) and stops cleanly."""

import threading
import time

from app.domain.contracts import Understanding, WorkerOutput
from app.runtime import worker
from app.schemas.agent import AgentChatRequest
from app.services import run_service


def test_serve_processes_a_run_and_stops_on_request(db, user, monkeypatch):
    def generate(role, prompt, data, output_type, cache_key):
        if role == "orchestrator":
            return Understanding(intent="action")
        event = {"date": "2030-01-07", "start": "10:00", "end": "11:00", "label": "In-process review"}
        return WorkerOutput(actions=[{"kind": "create", "event": event}])

    monkeypatch.setattr("app.integrations.openrouter.generate", generate)
    run = run_service.enqueue(db, user, AgentChatRequest(prompt="review at 10 am", request_id="in-process-1"))
    stop = threading.Event()
    thread = threading.Thread(target=worker.serve, args=(stop,), daemon=True)
    thread.start()
    try:
        deadline = time.time() + 90
        status = None
        while time.time() < deadline:
            db.expire_all()
            status = db.get(type(run), run.id).status
            if status == "awaiting_approval":
                break
            time.sleep(0.5)
        assert status == "awaiting_approval", status
    finally:
        stop.set()
        thread.join(timeout=30)
    assert not thread.is_alive()
