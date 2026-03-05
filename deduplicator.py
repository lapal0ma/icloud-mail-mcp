import aiosqlite
from datetime import datetime, timezone, timedelta

from database import DB_PATH

_AMOUNT_TOLERANCE = 0.02   # ±2%
_TIME_WINDOW_HOURS = 2


def _parse_dt(value: str) -> datetime:
    """Parse an ISO datetime string, ensuring it is timezone-aware."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def check_duplicate(
    amount: float,
    merchant: str,
    occurred_at: str,
    db_path: str = DB_PATH,
) -> dict:
    """
    Return {is_duplicate: bool, matched_transaction_id: str | None}.

    A duplicate requires ALL three conditions:
      - merchant matches (case-insensitive)
      - amount within ±2% of candidate
      - occurred_at within a 2-hour window of candidate
    """
    target_dt = _parse_dt(occurred_at)
    window = timedelta(hours=_TIME_WINDOW_HOURS)
    low = (target_dt - window).isoformat()
    high = (target_dt + window).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT transaction_id, amount, occurred_at
               FROM transactions
               WHERE LOWER(merchant) = LOWER(?)
                 AND occurred_at >= ?
                 AND occurred_at <= ?""",
            (merchant, low, high),
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        candidate_amount = row["amount"]
        if candidate_amount == 0:
            if amount == 0:
                return {"is_duplicate": True, "matched_transaction_id": row["transaction_id"]}
            continue
        if abs(amount - candidate_amount) / abs(candidate_amount) <= _AMOUNT_TOLERANCE:
            return {"is_duplicate": True, "matched_transaction_id": row["transaction_id"]}

    return {"is_duplicate": False, "matched_transaction_id": None}


async def merge_transactions(
    keep_id: str,
    discard_id: str,
    db_path: str = DB_PATH,
) -> dict:
    """
    Reassign all transaction_emails from discard_id to keep_id, then delete
    the discard transaction record.
    Returns {success: bool}.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            # Re-point emails that don't already exist on keep_id
            await db.execute(
                """UPDATE transaction_emails
                   SET transaction_id = ?
                   WHERE transaction_id = ?
                     AND email_id NOT IN (
                         SELECT email_id FROM transaction_emails WHERE transaction_id = ?
                     )""",
                (keep_id, discard_id, keep_id),
            )
            # Drop any remaining rows for discard_id (exact duplicates)
            await db.execute(
                "DELETE FROM transaction_emails WHERE transaction_id = ?",
                (discard_id,),
            )
            await db.execute(
                "DELETE FROM transactions WHERE transaction_id = ?",
                (discard_id,),
            )
            await db.commit()
        return {"success": True}
    except Exception:
        return {"success": False}
