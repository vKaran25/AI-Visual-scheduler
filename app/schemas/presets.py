from pydantic import BaseModel


class ApplyPresetRequest(BaseModel):
    clear_existing: bool = False


class CustomPresetRequest(BaseModel):
    name: str
    description: str = ""
    blocks: list[dict] | None = None

