import os
import sqlite3
from contextlib import closing
from pathlib import Path


def get_connection() -> sqlite3.Connection:
    database_path = os.environ.get("CRM_DB_PATH", "crm.sqlite3")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_db() -> None:
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    with closing(get_connection()) as connection:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
