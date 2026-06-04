from pydantic import BaseModel


class AgentChatRequest(BaseModel):
    prompt: str
    start_after: str | None = None
    slack: float = 0.0


class AgentDecisionRequest(BaseModel):
    session_id: str

