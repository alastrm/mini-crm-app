import sqlite3
from contextlib import asynccontextmanager, closing

from fastapi import FastAPI, HTTPException, Query

from app.db import get_connection, init_db
from app.schemas import (
    SQLITE_MAX_INTEGER,
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
