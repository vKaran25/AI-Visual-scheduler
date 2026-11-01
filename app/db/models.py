"""PostgreSQL records. LangGraph owns its separate checkpoint tables."""

import json
from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class ISODate(TypeDecorator):
    """Native DATE, exposed as ISO strings for the existing calendar API."""

    impl = Date
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return date.fromisoformat(value) if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return value.isoformat() if value else None


class JSONText(TypeDecorator):
    """Native JSONB behind the legacy JSON-string API."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return json.loads(value) if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return json.dumps(value) if value is not None else "null"


def timestamp():
    return Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    timezone: str = "UTC"
    timezone_confirmed: bool = False
    calendar_revision: int = 0
    created_at: datetime = timestamp()


class Block(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "start_minutes >= 0 AND end_minutes <= 1440 AND end_minutes > start_minutes",
            name="block_valid_interval",
        ),
        Index("ix_block_user_date", "user_id", "date"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    date: Optional[str] = Field(default=None, sa_column=Column(ISODate, index=True))
    start: str
    end: str
    start_minutes: int
    end_minutes: int
    starts_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    ends_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    timezone: str = "UTC"
    label: str
    color: str = "#d81b60"
    repeat_days_json: str = Field(default="[]", sa_column=Column(JSONText, nullable=False))
    is_gcal: bool = False
    is_default: bool = False
    is_pending: bool = False
    session_id: Optional[str] = Field(default=None, index=True)
    preset_source: Optional[str] = None
    revision: int = 1
    created_at: datetime = timestamp()


class CustomPreset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    description: str = ""
    blocks_json: str = Field(sa_column=Column(JSONText, nullable=False))
    created_at: datetime = timestamp()
    updated_at: datetime = timestamp()


class AgentSession(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    prompt: str = ""
    provider: str = "openrouter"
    status: str = "active"
    summary: str = ""
    title: str = "New conversation"
    calendar_snapshot: str = ""
    draft_revision: Optional[str] = None
    facts: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = timestamp()
    last_accessed_at: datetime = timestamp()
    finished_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class AgentMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    session_id: str = Field(foreign_key="agentsession.id", index=True)
    role: str
    content: str = Field(sa_column=Column(Text, nullable=False))
    operation_key: Optional[str] = Field(default=None, unique=True)
    created_at: datetime = timestamp()


class Memory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    type: str = Field(index=True)
    content: str
    chat_session_id: Optional[str] = Field(default=None, foreign_key="agentsession.id", index=True)
    created_at: datetime = timestamp()
    last_used_at: datetime = timestamp()


class MemoryProposal(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    content: str
    status: str = "pending"
    source_key: str = Field(unique=True)
    created_at: datetime = timestamp()


class AgentRun(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_run_request"),
        Index(
            "ix_one_live_run_per_conversation",
            "session_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'awaiting_input', 'awaiting_approval')"),
        ),
    )
    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    session_id: str = Field(foreign_key="agentsession.id", index=True)
    request_id: str
    graph_version: str = "calendar-v1"
    status: str = Field(default="queued", index=True)
    stage: str = "Queued"
    input: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    result: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    pending: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    lease_token: Optional[str] = None
    lease_until: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    model_attempts: int = 0
    active_seconds: float = 0
    cancel_requested: bool = False
    error: Optional[str] = None
    created_at: datetime = timestamp()
    updated_at: datetime = timestamp()


class RunEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="agentrun.id", index=True)
    stage: str
    details: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = timestamp()


class RunArtifact(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("run_id", "key", name="uq_artifact_key"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="agentrun.id", index=True)
    key: str
    kind: str
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = timestamp()


class Draft(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    run_id: str = Field(foreign_key="agentrun.id", index=True)
    revision: str = Field(default_factory=new_id)
    candidate_hash: str
    calendar_revision: int
    status: str = "pending"
    operations: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    preview: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = timestamp()


class OperationOutcome(SQLModel, table=True):
    key: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    result: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = timestamp()


class GoogleConnection(SQLModel, table=True):
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    credentials_ciphertext: str
    managed_calendar_id: Optional[str] = None
    last_sync_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    sync_error: Optional[str] = None
    revision: int = 1


class GoogleEventMapping(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "calendar_id", "event_id", name="uq_google_event"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    block_id: Optional[int] = Field(default=None, index=True)
    calendar_id: str
    event_id: str
    etag: Optional[str] = None
    imported: bool = False


class SyncJob(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    operation_key: str = Field(unique=True)
    action: str
    block_id: int
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="queued", index=True)
    attempts: int = 0
    available_at: datetime = timestamp()
    lease_token: Optional[str] = None
    lease_until: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    error: Optional[str] = None
    created_at: datetime = timestamp()


class EvalRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    name: str
    input_prompt: str = ""
    expected_json: str = Field(default="{}", sa_column=Column(JSONText, nullable=False))
    result_json: str = Field(default="{}", sa_column=Column(JSONText, nullable=False))
    metrics_json: str = Field(default="{}", sa_column=Column(JSONText, nullable=False))
    created_at: datetime = timestamp()
