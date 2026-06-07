import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db.models import CustomPreset, User
from app.services import scheduler_service

BUILTIN_PRESETS = [
    {
        "id": "blank",
        "name": "Blank",
        "description": "Start with an empty schedule.",
        "blocks": [],
    },
    {
        "id": "student",
        "name": "Student",
        "description": "Classes, homework, and sleep blocks for a typical weekday student routine.",
        "blocks": [
            {"label": "Sleep", "start": "00:00", "end": "06:30", "repeatDays": [0, 1, 2, 3, 4, 5, 6], "color": "#4527a0"},
            {"label": "Classes", "start": "08:30", "end": "13:30", "repeatDays": [0, 1, 2, 3, 4], "color": "#2e7d32"},
            {"label": "Homework", "start": "19:00", "end": "20:30", "repeatDays": [0, 1, 2, 3, 4], "color": "#0277bd"},
        ],
    },
    {
        "id": "exam_prep",
        "name": "Exam Prep",
        "description": "Focused study blocks with review and rest time.",
        "blocks": [
            {"label": "Deep Study", "start": "09:00", "end": "11:00", "repeatDays": [0, 1, 2, 3, 4], "color": "#7c6aff"},
            {"label": "Practice Problems", "start": "16:00", "end": "17:30", "repeatDays": [0, 1, 2, 3, 4], "color": "#f9a825"},
            {"label": "Review", "start": "20:00", "end": "21:00", "repeatDays": [0, 1, 2, 3, 4], "color": "#00695c"},
        ],
    },
    {
        "id": "working_professional",
        "name": "Working Professional",
        "description": "Workday structure with evening learning time.",
        "blocks": [
            {"label": "Work", "start": "09:00", "end": "17:00", "repeatDays": [0, 1, 2, 3, 4], "color": "#37474f"},
            {"label": "Commute / Reset", "start": "17:30", "end": "18:30", "repeatDays": [0, 1, 2, 3, 4], "color": "#e65100"},
            {"label": "Skill Building", "start": "20:00", "end": "21:00", "repeatDays": [1, 3], "color": "#7c6aff"},
        ],
    },
    {
        "id": "fitness_study",
        "name": "Fitness + Study",
        "description": "Balances exercise, study, and recovery.",
        "blocks": [
            {"label": "Workout", "start": "06:30", "end": "07:30", "repeatDays": [0, 2, 4], "color": "#d81b60"},
            {"label": "Study", "start": "19:00", "end": "20:30", "repeatDays": [0, 1, 2, 3, 4], "color": "#0277bd"},
            {"label": "Wind Down", "start": "22:00", "end": "22:30", "repeatDays": [0, 1, 2, 3, 4, 5, 6], "color": "#00695c"},
        ],
    },
]


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
    preset = get_preset(session, user, preset_id)
    if not preset:
        raise ValueError("Preset not found")
    if clear_existing:
        for block in scheduler_service.user_blocks(session, user.id):
            if not block.is_gcal:
                session.delete(block)
        session.commit()
    created = []
    for block_data in preset["blocks"]:
        block = scheduler_service.create_block(
            session,
            user,
            block_data,
            is_default=True,
            preset_source=preset_id,
            skip_overlap=clear_existing,
        )
        created.append(scheduler_service.block_to_dict(block))
    return {"preset": preset, "created": created}


def create_custom_preset(session: Session, user: User, name: str, description: str = "", blocks: list[dict] | None = None) -> CustomPreset:
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
    session.commit()
    session.refresh(preset)
    return preset


def update_custom_preset(session: Session, user: User, preset_id: int, name: str, description: str = "", blocks: list[dict] | None = None) -> CustomPreset | None:
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

