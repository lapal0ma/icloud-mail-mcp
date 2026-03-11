import aiosqlite
from datetime import datetime, timezone, timedelta

from database import DB_PATH

HKT = timezone(timedelta(hours=8))


def _now_hkt() -> str:
    return datetime.now(HKT).isoformat()


async def get_upcoming_bookings(days: int = 30, exclude_cancelled: bool = True, db_path: str = DB_PATH) -> list[dict]:
    now = _now_hkt()
    until = (datetime.now(HKT) + timedelta(days=days)).isoformat()
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            if exclude_cancelled:
                sql = """SELECT * FROM bookings
                         WHERE scheduled_at >= ? AND scheduled_at <= ?
                         AND status NOT IN ('cancelled', 'late_cancelled', 'teacher_cancelled')
                         ORDER BY scheduled_at"""
            else:
                sql = """SELECT * FROM bookings
                         WHERE scheduled_at >= ? AND scheduled_at <= ?
                         ORDER BY scheduled_at"""
            async with db.execute(sql, (now, until)) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Failed to fetch bookings", "detail": str(exc)}]


async def get_past_bookings(days: int = 30, exclude_cancelled: bool = False, db_path: str = DB_PATH) -> list[dict]:
    now = _now_hkt()
    since = (datetime.now(HKT) - timedelta(days=days)).isoformat()
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            if exclude_cancelled:
                sql = """SELECT * FROM bookings
                         WHERE scheduled_at >= ? AND scheduled_at < ?
                         AND status NOT IN ('cancelled', 'late_cancelled', 'teacher_cancelled')
                         ORDER BY scheduled_at DESC"""
            else:
                sql = """SELECT * FROM bookings
                         WHERE scheduled_at >= ? AND scheduled_at < ?
                         ORDER BY scheduled_at DESC"""
            async with db.execute(sql, (since, now)) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Failed to fetch past bookings", "detail": str(exc)}]


async def search_bookings(query: str, db_path: str = DB_PATH) -> list[dict]:
    pattern = f"%{query}%"
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM bookings
                   WHERE activity_name LIKE ? OR venue LIKE ?
                   ORDER BY scheduled_at DESC""",
                (pattern, pattern),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Search failed", "detail": str(exc)}]


async def get_booking_detail(booking_id: str, db_path: str = DB_PATH) -> dict:
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM bookings WHERE id = ?", (booking_id,)
            ) as cur:
                row = await cur.fetchone()
                if row is None:
                    return {"error": "Booking not found", "detail": booking_id}
                return dict(row)
    except Exception as exc:
        return {"error": "Failed to fetch booking", "detail": str(exc)}
