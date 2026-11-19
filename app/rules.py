import sqlite3
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException


ALMATY = ZoneInfo("Asia/Almaty")
MEETING_DURATION = timedelta(minutes=60)


def check_working_hours(start_at: datetime) -> None:
    try:
        local_start = start_at.astimezone(ALMATY)
        local_end = (start_at + MEETING_DURATION).astimezone(ALMATY)
    except (ValueError, OverflowError) as error:
        raise HTTPException(422, "Meeting time is outside the supported date range") from error
    if local_start.weekday() >= 5:
        raise HTTPException(422, "Meetings are only allowed Monday to Friday")
    if (
        local_start.time() < time(9)
        or local_end.date() != local_start.date()
        or local_end.time() > time(18)
    ):
        raise HTTPException(422, "The full 60-minute meeting must fit within 09:00-18:00 Asia/Almaty")


def check_overlaps(
    connection: sqlite3.Connection,
    company_id: int,
    manager_id: int,
    start_at: datetime,
    meeting_id: int | None = None,
) -> None:
    end_at = start_at + MEETING_DURATION
    meetings = connection.execute(
        "SELECT manager_id, start_at FROM meetings WHERE status = 'scheduled' "
        "AND (manager_id = ? OR company_id = ?) AND (? IS NULL OR id != ?)",
        (manager_id, company_id, meeting_id, meeting_id),
    ).fetchall()
    for meeting in meetings:
        existing_start = datetime.fromisoformat(meeting["start_at"])
        existing_end = existing_start + MEETING_DURATION
        if existing_start < end_at and start_at < existing_end:
            if meeting["manager_id"] == manager_id:
                raise HTTPException(409, "Manager already has a meeting at this time")
            raise HTTPException(409, "Company already has a meeting at this time")
