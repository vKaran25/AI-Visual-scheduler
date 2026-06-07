from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=utc_now)


class Block(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    date: Optional[str] = Field(default=None, index=True)
    start: str
    end: str
    start_minutes: int
    end_minutes: int
    label: str
    color: str = "#d81b60"
    repeat_days_json: str = "[]"
    is_gcal: bool = False
    is_default: bool = False
    is_pending: bool = False
    session_id: Optional[str] = Field(default=None, index=True)
    preset_source: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class CustomPreset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    description: str = ""
    blocks_json: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentSession(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    prompt: str
    provider: str = "nvidia_nim"
    status: str = "pending"
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class AgentMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    session_id: str = Field(foreign_key="agentsession.id", index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class Memory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    type: str = Field(index=True)
    content: str
    created_at: datetime = Field(default_factory=utc_now)
    last_used_at: datetime = Field(default_factory=utc_now)


class EvalRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    name: str
    input_prompt: str = ""
    expected_json: str = "{}"
    result_json: str = "{}"
    metrics_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)

