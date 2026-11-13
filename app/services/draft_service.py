"""Pure previews followed by revision-bound atomic calendar commands."""

import hashlib
import json

from sqlmodel import Session, select

from app.db.models import Draft, OperationOutcome, RunEvent, User
from app.db.transactions import lock_calendar
from app.domain.contracts import Action
from app.domain.time_utils import validate_time_range, weekday_for_date
from app.services import scheduler_service as calendar


class StaleDraft(ValueError):
    pass


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def overlaps(a, b):
    first, last = validate_time_range(a["start"], a["end"])
    other_first, other_last = validate_time_range(b["start"], b["end"])
    if first >= other_last or other_first >= last:
        return False
    ar, br = a.get("repeatDays", []), b.get("repeatDays", [])
    if ar and br:
        return bool(set(ar) & set(br))
    if ar:
        return weekday_for_date(b["date"]) in ar
    if br:
        return weekday_for_date(a["date"]) in br
    return a["date"] == b["date"]


def prepare(db: Session, user: User, actions: list[Action]) -> dict:
    from app.services import preset_service

    existing = {b.id: calendar.block_to_dict(b) for b in calendar.user_blocks(db, user.id)}
    operations = []
    for action in actions:
        value = action.model_dump(mode="json")
        if action.kind in ("preset_apply", "preset_remove"):
            preset = preset_service.get_preset(db, user, action.preset_id)
            if preset is None:
                raise ValueError("Preset not found")
            removals = [
                b
                for b in existing.values()
                if not b["is_gcal"]
                and (
                    action.clear_existing
                    or (action.kind == "preset_remove" and b["preset_source"] == action.preset_id)
                )
            ]
            operations.extend(
                {"kind": "delete", "block_id": b["id"], "expected_revision": b["revision"], "before": b}
                for b in removals
            )
            if action.kind == "preset_apply":
                operations.extend(
                    {"kind": "create", "event": block, "preset_source": action.preset_id}
                    for block in preset["blocks"]
                )
        elif action.kind == "preset_save":
            value["blocks"] = [
                {key: b[key] for key in ("date", "start", "end", "label", "color", "repeatDays")}
                for b in existing.values()
                if not b["is_gcal"]
            ]
            operations.append(value)
        else:
            operations.append(value)
    normalized = []
    for operation in operations:
        metadata = {key: operation[key] for key in ("preset_source", "blocks") if key in operation}
        clean = {key: value for key, value in operation.items() if key in Action.model_fields}
        normalized.append({**Action.model_validate(clean).model_dump(mode="json"), **metadata})
    operations = normalized
    touched = set()
    for operation in operations:
        if operation["kind"] in ("update", "delete"):
            block_id = operation["block_id"]
            if block_id in touched:
                raise ValueError("An event cannot be changed twice in one proposal")
            touched.add(block_id)
            old = existing.get(block_id)
            if old is None or old["is_gcal"]:
                raise ValueError("Only your own app-created events can be changed")
            if old["revision"] != operation["expected_revision"]:
                raise StaleDraft("An event changed since this proposal was prepared")
            operation["before"] = old
    final = [b for key, b in existing.items() if key not in touched]
    from app.domain.contracts import EventData
    from app.domain.time import event_instants

    for operation in operations:
        if operation["kind"] not in ("create", "update"):
            continue
        data = EventData.model_validate(operation["event"]).model_dump(mode="json")
        if data["date"] and not data["repeatDays"]:
            event_instants(data["date"], data["start"], data["end"], user.timezone)
        operation["event"] = data
        clash = next((b for b in final if overlaps(data, b)), None)
        if clash:
            raise ValueError(
                f"{data['label']} ({data['start']}-{data['end']}) overlaps {clash.get('label') or 'another event'} "
                f"({clash['start']}-{clash['end']})"
            )
        final.append(data)
    scheduled = [o["event"] for o in operations if o["kind"] in ("create", "update")]

    def minutes(event):
        if event.get("date") and not event.get("repeatDays"):
            first, last = event_instants(event["date"], event["start"], event["end"], user.timezone)
            return (last - first).total_seconds() / 60
        first, last = validate_time_range(event["start"], event["end"])
        return last - first

    preview = {
        "changes": [
            {**op, "event": {**op["event"], "durationMinutes": minutes(op["event"])}}
            if op["kind"] in ("create", "update")
            else op
            for op in operations
        ],
        "scheduled": scheduled,
        "num_blocks": len(scheduled),
        "total_hours": round(sum(minutes(b) for b in scheduled) / 60, 2),
        "calendar_revision": user.calendar_revision,
    }
    return {"operations": operations, "preview": preview, "hash": digest(operations)}


def stage(db: Session, user: User, run_id: str, prepared: dict) -> Draft:
    from app.runtime.context import fence

    fence(db)
    owner = lock_calendar(db, user.id)
    previous = list(db.exec(select(Draft).where(Draft.run_id == run_id, Draft.status == "pending")).all())
    for draft in previous:
        if draft.candidate_hash == prepared["hash"]:
            return draft
        draft.status = "superseded"
        db.add(draft)
    draft = Draft(
        user_id=user.id,
        run_id=run_id,
        candidate_hash=prepared["hash"],
        calendar_revision=owner.calendar_revision,
        operations=prepared["operations"],
        preview=prepared["preview"],
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def decide(db: Session, user: User, draft_id: str, revision: str, accept: bool):
    from app.runtime.context import fence

    fence(db)
    lock_calendar(db, user.id)
    outcome_key = f"draft:{draft_id}:{revision}"
    previous = db.get(OperationOutcome, outcome_key)
    if previous:
        if previous.user_id != user.id:
            raise ValueError("Draft not found")
        saved_draft = db.get(Draft, draft_id)
        db.add(
            RunEvent(
                run_id=saved_draft.run_id,
                stage="Recovered committed result",
                details={"operation_key": outcome_key},
            )
        )
        db.commit()
        return previous.result
    draft = db.exec(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id).with_for_update()
    ).first()
    if draft is None or draft.revision != revision or draft.status != "pending":
        raise StaleDraft("This draft was replaced; review the latest preview")
    if not accept:
        result = {"success": True, "response": "Draft rejected. No calendar changes were made.", "count": 0}
        draft.status = "rejected"
    else:
        originals = []
        for op in draft.operations:
            clean = {k: v for k, v in op.items() if k in Action.model_fields}
            originals.append(Action.model_validate(clean))
        checked = prepare(db, user, originals)
        for original, verified in zip(draft.operations, checked["operations"]):
            if "preset_source" in original:
                verified["preset_source"] = original["preset_source"]
        checked["hash"] = digest(checked["operations"])
        if checked["hash"] != draft.candidate_hash:
            raise StaleDraft("The calendar or preset changed; a new preview is required")
        from app.services import preset_service

        # Remove first, then update/create against the fully validated final state.
        for op in draft.operations:
            if op["kind"] == "delete":
                calendar.delete_block(
                    db, user, op["block_id"], commit=False, expected_revision=op["expected_revision"]
                )
        for op in draft.operations:
            if op["kind"] == "update":
                calendar.update_block(
                    db,
                    user,
                    op["block_id"],
                    {**op["event"], "revision": op["expected_revision"]},
                    commit=False,
                    skip_overlap=True,
                )
            elif op["kind"] == "create":
                calendar.create_block(
                    db,
                    user,
                    op["event"],
                    commit=False,
                    skip_overlap=True,
                    preset_source=op.get("preset_source"),
                    is_default=bool(op.get("preset_source")),
                )
            elif op["kind"] == "preset_save":
                preset_service.create_custom_preset(db, user, op["name"], blocks=op["blocks"], commit=False)
        draft.status = "confirmed"
        result = {
            "success": True,
            "response": "Approved calendar changes were saved. Google synchronization is queued when connected.",
            "count": len(draft.operations),
            "sync_status": "queued",
            "saved_event_date": next(
                (event["date"] for event in checked["preview"]["scheduled"] if event["date"]),
                None,
            ),
        }
    db.add(draft)
    db.add(OperationOutcome(key=outcome_key, user_id=user.id, result=result))
    db.commit()
    return result


def overlays(db, user, date_str):
    from app.db.models import AgentRun
    from app.domain.time_utils import time_to_minutes, weekday_for_date

    rows = db.exec(
        select(Draft)
        .join(AgentRun, Draft.run_id == AgentRun.id)
        .where(Draft.user_id == user.id, Draft.status == "pending", AgentRun.status == "awaiting_approval")
    ).all()
    result = []
    for draft in rows:
        run = db.get(AgentRun, draft.run_id)
        for index, event in enumerate(draft.preview.get("scheduled", [])):
            repeats = event.get("repeatDays", [])
            if (weekday_for_date(date_str) in repeats) if repeats else (event.get("date") == date_str):
                result.append(
                    {
                        **event,
                        "date": date_str,
                        "id": -int(draft.id[:10], 16) - index,
                        "startMinutes": time_to_minutes(event["start"]),
                        "endMinutes": time_to_minutes(event["end"]),
                        "is_pending": True,
                        "is_gcal": False,
                        "is_default": False,
                        "run_id": run.id,
                        "session_id": run.session_id,
                        "draft_id": draft.id,
                        "revision": draft.revision,
                    }
                )
    return result
