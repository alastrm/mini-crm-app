from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CompanyStatus = Literal["new", "no_answer", "refused", "meeting_set"]
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
