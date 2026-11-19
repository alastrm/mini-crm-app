from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CompanyStatus = Literal["new", "no_answer", "refused", "meeting_set"]
CallResult = Literal["no_answer", "refused", "meeting_set"]
SQLITE_MAX_INTEGER = 2**63 - 1


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("start_at must be a UTC ISO 8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("start_at must use UTC (Z or +00:00)")
    return parsed.astimezone(UTC)


class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    bin: str = Field(pattern=r"^[0-9]{12}$")
    phone: str = Field(min_length=1, max_length=50)


class Company(CompanyCreate):
    id: int
    status: CompanyStatus


class CompanyPage(BaseModel):
    items: list[Company]
    total: int
    page: int
    page_size: int


class CallCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: int = Field(gt=0, le=SQLITE_MAX_INTEGER, strict=True)
    result: CallResult
    meeting_id: int | None = Field(default=None, gt=0, le=SQLITE_MAX_INTEGER, strict=True)

    @model_validator(mode="after")
    def check_meeting_id(self):
        if self.result == "meeting_set" and self.meeting_id is None:
            raise ValueError("meeting_set requires meeting_id")
        if self.result != "meeting_set" and self.meeting_id is not None:
            raise ValueError("meeting_id is only allowed for meeting_set")
        return self


class Call(CallCreate):
    id: int
    created_at: datetime


class MeetingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: int = Field(gt=0, le=SQLITE_MAX_INTEGER, strict=True)
    manager_id: int = Field(gt=0, le=SQLITE_MAX_INTEGER, strict=True)
    start_at: datetime

    @field_validator("start_at", mode="before")
    @classmethod
    def check_start_at(cls, value):
        return parse_utc(value)


class MeetingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime | None = None
    status: Literal["cancelled"] | None = None

    @field_validator("start_at", mode="before")
    @classmethod
    def check_start_at(cls, value):
        return parse_utc(value)

    @model_validator(mode="after")
    def check_action(self):
        if len(self.model_fields_set) != 1 or (self.start_at is None and self.status is None):
            raise ValueError("Provide exactly one action: start_at or status='cancelled'")
        return self


class Meeting(BaseModel):
    id: int
    company_id: int
    manager_id: int
    start_at: datetime
    original_start_at: datetime
    created_at: datetime
    status: Literal["scheduled", "cancelled"]
