from typing import Literal

from pydantic import BaseModel


class MemoryRequest(BaseModel):
    type: Literal["pref", "preference", "fact"] = "pref"
    content: str
    chat_session_id: str | None = None

