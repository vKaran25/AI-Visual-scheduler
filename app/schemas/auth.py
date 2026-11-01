from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator


class AuthRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class UserResponse(BaseModel):
    id: int
    email: str
    timezone: str = "UTC"
    timezone_confirmed: bool = False


class TimezoneRequest(BaseModel):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA timezone") from exc
        return value
