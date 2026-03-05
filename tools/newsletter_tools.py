import aiosqlite
from datetime import datetime, timezone, timedelta

from database import DB_PATH

HKT = timezone(timedelta(hours=8))


def _since(days: int) -> str:
    return (datetime.now(HKT) - timedelta(days=days)).isoformat()


async def get_newsletter_activities(days: int = 30, db_path: str = DB_PATH) -> list[dict]:
    since = _since(days)
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM newsletter_activities
                   WHERE newsletter_date >= ?
                   ORDER BY newsletter_date DESC""",
                (since,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Failed to fetch activities", "detail": str(exc)}]


async def search_newsletter_activities(query: str, db_path: str = DB_PATH) -> list[dict]:
    pattern = f"%{query}%"
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM newsletter_activities
                   WHERE title LIKE ?
                      OR description LIKE ?
                      OR sender_org LIKE ?
                   ORDER BY newsletter_date DESC""",
                (pattern, pattern, pattern),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Search failed", "detail": str(exc)}]
