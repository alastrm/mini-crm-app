import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query

from app.db import get_connection, init_db
from app.schemas import (
    SQLITE_MAX_INTEGER,
    Call,
    CallCreate,
    Company,
    CompanyCreate,
    CompanyPage,
    CompanyStatus,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Mini CRM", lifespan=lifespan)


@app.post("/companies", response_model=Company, status_code=201)
def create_company(company: CompanyCreate):
    with closing(get_connection()) as connection:
        try:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO companies (name, bin, phone) VALUES (?, ?, ?)",
                    (company.name, company.bin, company.phone),
                )
                row = connection.execute(
                    "SELECT * FROM companies WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise HTTPException(409, "A company with this BIN already exists") from error
            raise
    return dict(row)


@app.get("/companies", response_model=CompanyPage)
def list_companies(
    status: CompanyStatus | None = None,
    page: int = Query(default=1, ge=1, le=SQLITE_MAX_INTEGER // 100),
    page_size: int = Query(default=20, ge=1, le=100),
):
    with closing(get_connection()) as connection:
        total = connection.execute(
            "SELECT count(*) FROM companies WHERE (? IS NULL OR status = ?)",
            (status, status),
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM companies WHERE (? IS NULL OR status = ?) "
            "ORDER BY id LIMIT ? OFFSET ?",
            (status, status, page_size, (page - 1) * page_size),
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/calls", response_model=Call, status_code=201)
def create_call(call: CallCreate):
    with closing(get_connection()) as connection:
        with connection:
            company = connection.execute(
                "SELECT id FROM companies WHERE id = ?", (call.company_id,)
            ).fetchone()
            if company is None:
                raise HTTPException(404, "Company not found")
            if call.result == "meeting_set":
                meeting = connection.execute(
                    "SELECT company_id, status FROM meetings WHERE id = ?",
                    (call.meeting_id,),
                ).fetchone()
                if (
                    meeting is None
                    or meeting["company_id"] != call.company_id
                    or meeting["status"] != "scheduled"
                ):
                    raise HTTPException(422, "meeting_id must reference an active meeting of this company")
            cursor = connection.execute(
                "INSERT INTO calls (company_id, result, meeting_id, created_at) VALUES (?, ?, ?, ?)",
                (call.company_id, call.result, call.meeting_id, datetime.now(UTC).isoformat()),
            )
            connection.execute(
                "UPDATE companies SET status = ? WHERE id = ?",
                (call.result, call.company_id),
            )
            row = connection.execute(
                "SELECT * FROM calls WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
    return dict(row)
