import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db.models import CustomPreset, User
from app.domain.presets import BUILTIN_PRESETS
from app.services import scheduler_service


def list_presets(session: Session, user: User) -> list[dict]:
    custom = session.exec(select(CustomPreset).where(CustomPreset.user_id == user.id)).all()
    custom_items = [
        {
            "id": f"custom:{preset.id}",
            "name": preset.name,
            "description": preset.description,
            "blocks": json.loads(preset.blocks_json),
            "custom": True,
        }
        for preset in custom
    ]
    return [{**preset, "custom": False} for preset in BUILTIN_PRESETS] + custom_items


def get_preset(session: Session, user: User, preset_id: str) -> dict | None:
    if preset_id.startswith("custom:"):
        custom_id = int(preset_id.split(":", 1)[1])
        preset = session.get(CustomPreset, custom_id)
        if not preset or preset.user_id != user.id:
            return None
        return {
            "id": preset_id,
            "name": preset.name,
            "description": preset.description,
            "blocks": json.loads(preset.blocks_json),
            "custom": True,
        }
    return next((preset for preset in BUILTIN_PRESETS if preset["id"] == preset_id), None)


def apply_preset(session: Session, user: User, preset_id: str, clear_existing: bool = False) -> dict:
    from app.db.transactions import lock_calendar

    lock_calendar(session, user.id)
    preset = get_preset(session, user, preset_id)
    if not preset:
        raise ValueError("Preset not found")
    if user.id is None:
        raise ValueError("User must be saved before applying presets")
    # Validate the entire preset before touching the user's existing schedule.
    for block_data in preset["blocks"]:
        if not isinstance(block_data, dict):
            raise ValueError("Preset blocks must be objects")
        scheduler_service.validate_time_range(block_data.get("start"), block_data.get("end"))
        if not scheduler_service.normalize_repeat_days(block_data.get("repeatDays")):
            if not block_data.get("date"):
                raise ValueError("One-time preset blocks need a date")
            scheduler_service.validate_calendar_date(block_data["date"])
    try:
        if clear_existing:
            for block in scheduler_service.user_blocks(session, user.id):
                if not block.is_gcal:
                    scheduler_service.delete_block(session, user, block.id, commit=False)
            session.flush()
        created = []
        for block_data in preset["blocks"]:
            block = scheduler_service.create_block(
                session,
                user,
                block_data,
                is_default=True,
                preset_source=preset_id,
                commit=False,
            )
            created.append(scheduler_service.block_to_dict(block))
        session.commit()
        return {"preset": preset, "created": created}
    except Exception:
        session.rollback()
        raise


def create_custom_preset(
    session: Session,
    user: User,
    name: str,
    description: str = "",
    blocks: list[dict] | None = None,
    *,
    commit=True,
) -> CustomPreset:
    if user.id is None:
        raise ValueError("User must be saved before creating presets")
    if blocks is None:
        blocks = [
            {
                "label": block.label,
                "start": block.start,
                "end": block.end,
                "repeatDays": json.loads(block.repeat_days_json or "[]"),
                "date": block.date,
                "color": block.color,
            }
            for block in scheduler_service.user_blocks(session, user.id)
            if not block.is_gcal and not block.is_pending
        ]
    preset = CustomPreset(user_id=user.id, name=name, description=description, blocks_json=json.dumps(blocks))
    session.add(preset)
    session.flush()
    if commit:
        session.commit()
        session.refresh(preset)
    return preset


def update_custom_preset(
    session: Session,
    user: User,
    preset_id: int,
    name: str,
    description: str = "",
    blocks: list[dict] | None = None,
) -> CustomPreset | None:
    preset = session.get(CustomPreset, preset_id)
    if not preset or preset.user_id != user.id:
        return None
    preset.name = name
    preset.description = description
    if blocks is not None:
        preset.blocks_json = json.dumps(blocks)
    preset.updated_at = datetime.now(timezone.utc)
    session.add(preset)
    session.commit()
    session.refresh(preset)
    return preset


def delete_custom_preset(session: Session, user: User, preset_id: int) -> bool:
    preset = session.get(CustomPreset, preset_id)
    if not preset or preset.user_id != user.id:
        return False
    session.delete(preset)
    session.commit()
    return True


def remove_preset_blocks(session: Session, user: User, preset_id: str) -> int:
    return scheduler_service.delete_blocks_by_flags(session, user, preset_source=preset_id)
