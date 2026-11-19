from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CompanyStatus = Literal["new", "no_answer", "refused", "meeting_set"]
CallResult = Literal["no_answer", "refused", "meeting_set"]
SQLITE_MAX_INTEGER = 2**63 - 1


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
