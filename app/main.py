import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import UTC, date as Date, datetime, time, timedelta

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from app.db import get_connection, init_db
from app.rules import ALMATY, check_overlaps, check_working_hours
from app.schemas import (
    SQLITE_MAX_INTEGER,
    Call,
    CallCreate,
    Company,
    CompanyCreate,
    CompanyPage,
    CompanyStatus,
    Meeting,
    MeetingCreate,
    MeetingPatch,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Mini CRM", lifespan=lifespan)


@app.exception_handler(sqlite3.OperationalError)
def handle_database_lock(request: Request, error: sqlite3.OperationalError):
    if error.sqlite_errorname.startswith("SQLITE_BUSY") or error.sqlite_errorname.startswith("SQLITE_LOCKED"):
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is busy. Please retry the request shortly."},
            headers={"Retry-After": "1"},
        )
    raise error


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
            connection.execute("BEGIN IMMEDIATE")
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


@app.post("/meetings", response_model=Meeting, status_code=201)
def create_meeting(meeting: MeetingCreate):
    start_at = meeting.start_at.isoformat(timespec="microseconds")
    with closing(get_connection()) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            company = connection.execute(
                "SELECT id FROM companies WHERE id = ?", (meeting.company_id,)
            ).fetchone()
            if company is None:
                raise HTTPException(404, "Company not found")
            manager = connection.execute(
                "SELECT id FROM managers WHERE id = ?", (meeting.manager_id,)
            ).fetchone()
            if manager is None:
                raise HTTPException(404, "Manager not found")
            check_working_hours(meeting.start_at)
            check_overlaps(connection, meeting.company_id, meeting.manager_id, meeting.start_at)
            cursor = connection.execute(
                "INSERT INTO meetings "
                "(company_id, manager_id, start_at, original_start_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    meeting.company_id,
                    meeting.manager_id,
                    start_at,
                    start_at,
                    datetime.now(UTC).isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM meetings WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
    return dict(row)


@app.patch("/meetings/{id}", response_model=Meeting)
def update_meeting(
    update: MeetingPatch,
    id: int = Path(gt=0, le=SQLITE_MAX_INTEGER),
):
    with closing(get_connection()) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            meeting = connection.execute(
                "SELECT * FROM meetings WHERE id = ?", (id,)
            ).fetchone()
            if meeting is None:
                raise HTTPException(404, "Meeting not found")
            if update.start_at is not None:
                if meeting["status"] == "cancelled":
                    raise HTTPException(409, "Cancelled meetings cannot be rescheduled")
                check_working_hours(update.start_at)
                check_overlaps(
                    connection, meeting["company_id"], meeting["manager_id"], update.start_at, id
                )
                connection.execute(
                    "UPDATE meetings SET start_at = ? WHERE id = ?",
                    (update.start_at.isoformat(timespec="microseconds"), id),
                )
            else:
                connection.execute(
                    "UPDATE meetings SET status = 'cancelled' WHERE id = ?", (id,)
                )
            row = connection.execute("SELECT * FROM meetings WHERE id = ?", (id,)).fetchone()
    return dict(row)


@app.get("/managers/{id}/schedule", response_model=list[Meeting])
def get_schedule(
    id: int = Path(gt=0, le=SQLITE_MAX_INTEGER),
    date: str = Query(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
):
    try:
        day = Date.fromisoformat(date)
        local_start = datetime.combine(day, time.min, tzinfo=ALMATY)
        start_at = local_start.astimezone(UTC).isoformat(timespec="microseconds")
        end_at = (local_start + timedelta(days=1)).astimezone(UTC).isoformat(timespec="microseconds")
    except (ValueError, OverflowError) as error:
        raise HTTPException(422, "date must be a supported calendar date in YYYY-MM-DD format") from error

    with closing(get_connection()) as connection:
        manager = connection.execute("SELECT id FROM managers WHERE id = ?", (id,)).fetchone()
        if manager is None:
            raise HTTPException(404, "Manager not found")
        rows = connection.execute(
            "SELECT * FROM meetings WHERE manager_id = ? AND status = 'scheduled' "
            "AND start_at >= ? AND start_at < ? ORDER BY start_at, id",
            (id, start_at, end_at),
        ).fetchall()
    return [dict(row) for row in rows]
