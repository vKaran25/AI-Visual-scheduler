"""Synchronization intents written inside the calendar transaction."""

import json
from zoneinfo import ZoneInfo

from sqlmodel import Session

from app.db.models import Block, GoogleConnection, SyncJob


def enqueue(db: Session, block: Block, action: str) -> None:
    if block.is_gcal or block.is_pending or db.get(GoogleConnection, block.user_id) is None:
        return
    payload = {
        "id": block.id,
        "date": block.date,
        "start": block.start,
        "end": block.end,
        "label": block.label,
        "repeatDays": json.loads(block.repeat_days_json),
        "timezone": block.timezone,
        "revision": block.revision,
        "anchor_date": block.created_at.astimezone(ZoneInfo(block.timezone)).date().isoformat(),
    }
    db.add(
        SyncJob(
            user_id=block.user_id,
            block_id=block.id,
            action=action,
            operation_key=f"block:{block.id}:revision:{block.revision}:{action}",
            payload=payload,
        )
    )
