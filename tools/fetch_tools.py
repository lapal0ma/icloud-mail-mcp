import aiosqlite
from datetime import datetime, timezone, timedelta

from database import DB_PATH

HKT = timezone(timedelta(hours=8))


async def get_unclassified_emails(limit: int = 50, db_path: str = DB_PATH) -> list[dict]:
    """Return raw_emails where processed=0 (never returns processed=-1 rows)."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, sender, subject, body_text, received_at
               FROM raw_emails
               WHERE processed = 0
               ORDER BY received_at
               LIMIT ?""",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_classified_emails(
    category: str, days: int = 7, db_path: str = DB_PATH
) -> list[dict]:
    """Return emails of a given category received within the last N days."""
    since = (datetime.now(HKT) - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, sender, subject, body_text, received_at,
                      category, category_confidence
               FROM raw_emails
               WHERE category = ?
                 AND received_at >= ?
               ORDER BY received_at DESC""",
            (category, since),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_email_detail(email_id: str, db_path: str = DB_PATH) -> dict | None:
    """Return full detail for a single email. Never returns processed=-1 emails."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM raw_emails WHERE id = ? AND processed != -1",
            (email_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
