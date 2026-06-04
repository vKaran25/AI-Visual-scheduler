from pydantic import BaseModel


class BlockRequest(BaseModel):
    date: str | None = None
    start: str
    end: str
    label: str = "Busy"
    color: str = "#d81b60"
    repeatDays: list[int] = []


class DefaultBlocksRequest(BaseModel):
    enabled: bool


class FreeBlocksResponse(BaseModel):
    allocated: list[dict]
    totalAllocated: float
    requested: float
    fulfilled: bool
    missing: float

