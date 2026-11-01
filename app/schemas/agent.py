from pydantic import BaseModel, ConfigDict, Field


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=12000)
    start_after: str | None = None
    slack: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    session_id: str | None = None
    request_id: str | None = Field(default=None, max_length=128)


class AgentDecisionRequest(BaseModel):
    session_id: str
    draft_id: str
    revision: str


class ResumeRequest(BaseModel):
    interrupt_id: str
    response: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=1, max_length=128)


class MemoryDecisionRequest(BaseModel):
    accept: bool


class SessionSummary(BaseModel):
    session_id: str
    title: str
    status: str
    created_at: str
