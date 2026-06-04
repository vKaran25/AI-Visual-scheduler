from pydantic import BaseModel


class MemoryRequest(BaseModel):
    type: str = "preference"
    content: str

