from pydantic import BaseModel


class MessageResponse(BaseModel):
    success: bool = True
    message: str | None = None

