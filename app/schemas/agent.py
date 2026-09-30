import math

from pydantic import BaseModel, field_validator


class AgentChatRequest(BaseModel):
    prompt: str
    start_after: str | None = None
    slack: float = 0.0
    session_id: str | None = None   # Omit to start a NEW session; pass to CONTINUE an existing one

    @field_validator("slack")
    @classmethod
    def validate_slack(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("slack must be a finite non-negative number")
        return value


class AgentDecisionRequest(BaseModel):
    session_id: str
    draft_id: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    title: str
    status: str
    created_at: str
