import time
import aiosqlite
from datetime import datetime, timezone, timedelta

from database import DB_PATH
from imap_client import fetch_new_emails

HKT = timezone(timedelta(hours=8))

_last_sync_at: str | None = None


async def sync_now(db_path: str = DB_PATH) -> dict:
    global _last_sync_at
    start = time.monotonic()
    try:
        stored = await fetch_new_emails(db_path=db_path)
        _last_sync_at = datetime.now(HKT).isoformat()
        return {
            "synced_count": len(stored),
            "duration_seconds": round(time.monotonic() - start, 2),
        }
    except Exception as exc:
        return {"error": "Sync failed", "detail": str(exc)}


async def get_sync_status(db_path: str = DB_PATH) -> dict:
    try:
        async with aiosqlite.connect(db_path) as db:
            async def scalar(sql: str, params: tuple = ()) -> int:
                async with db.execute(sql, params) as cur:
                    row = await cur.fetchone()
                    return row[0] if row else 0

            total = await scalar("SELECT COUNT(*) FROM raw_emails")
            unclassified = await scalar("SELECT COUNT(*) FROM raw_emails WHERE processed = 0")
            sensitive = await scalar(
                "SELECT COUNT(*) FROM raw_emails WHERE processed = -1"
            )
            rule_filtered = await scalar(
                "SELECT COUNT(*) FROM raw_emails WHERE processed = -2"
            )
            queue = await scalar("SELECT COUNT(*) FROM unprocessed_queue")

        return {
            "last_sync_at": _last_sync_at,
            "total_emails": total,
            "unclassified_count": unclassified,
            "sensitive_filtered_count": sensitive,
            "rule_filtered_count": rule_filtered,
            "unprocessed_queue_count": queue,
        }
    except Exception as exc:
        return {"error": "Failed to fetch status", "detail": str(exc)}


async def get_unprocessed_queue(limit: int = 20, db_path: str = DB_PATH) -> list[dict]:
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT q.id, q.email_id, q.reason, q.created_at,
                          e.sender, e.subject, e.received_at
                   FROM unprocessed_queue q
                   LEFT JOIN raw_emails e ON e.id = q.email_id
                   ORDER BY q.created_at
                   LIMIT ?""",
                (limit,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Failed to fetch queue", "detail": str(exc)}]
