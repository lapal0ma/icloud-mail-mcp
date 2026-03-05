import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional

from database import DB_PATH, insert_transaction, link_transaction_email

HKT = timezone(timedelta(hours=8))


def _now_hkt() -> str:
    return datetime.now(HKT).isoformat()


def _since(days: int) -> str:
    return (datetime.now(HKT) - timedelta(days=days)).isoformat()


async def get_recent_transactions(
    days: int = 30,
    category: Optional[str] = None,
    db_path: str = DB_PATH,
) -> list[dict]:
    since = _since(days)
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            if category:
                sql = """SELECT * FROM transactions
                         WHERE occurred_at >= ? AND category = ?
                         ORDER BY occurred_at DESC"""
                params = (since, category)
            else:
                sql = "SELECT * FROM transactions WHERE occurred_at >= ? ORDER BY occurred_at DESC"
                params = (since,)
            async with db.execute(sql, params) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Failed to fetch transactions", "detail": str(exc)}]


async def search_transactions(query: str, db_path: str = DB_PATH) -> list[dict]:
    pattern = f"%{query}%"
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM transactions
                   WHERE merchant LIKE ? OR notes LIKE ?
                   ORDER BY occurred_at DESC""",
                (pattern, pattern),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Search failed", "detail": str(exc)}]


async def get_transaction_summary(days: int = 30, db_path: str = DB_PATH) -> list[dict]:
    since = _since(days)
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT category,
                          currency,
                          COUNT(*) AS count,
                          ROUND(SUM(amount), 2) AS total
                   FROM transactions
                   WHERE occurred_at >= ?
                   GROUP BY category, currency
                   ORDER BY total DESC""",
                (since,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        return [{"error": "Summary failed", "detail": str(exc)}]


async def split_transaction(
    transaction_id: str,
    split_into: list[dict],
    db_path: str = DB_PATH,
) -> dict:
    """
    Split one transaction into multiple.
    Each item in split_into must have: amount, merchant, category.
    Optional per-item keys: currency, payment_method, reference_no, notes.
    occurred_at is inherited from the original transaction.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)
            ) as cur:
                original = await cur.fetchone()
            if not original:
                return {"error": "Transaction not found", "detail": transaction_id}
            original = dict(original)

            async with db.execute(
                "SELECT email_id, role FROM transaction_emails WHERE transaction_id = ?",
                (transaction_id,),
            ) as cur:
                email_links = [dict(r) for r in await cur.fetchall()]

        new_ids = []
        for part in split_into:
            new_id = await insert_transaction(
                amount=part["amount"],
                merchant=part["merchant"],
                occurred_at=original["occurred_at"],
                currency=part.get("currency", original["currency"]),
                category=part.get("category"),
                payment_method=part.get("payment_method", original["payment_method"]),
                reference_no=part.get("reference_no", original["reference_no"]),
                notes=part.get("notes"),
                db_path=db_path,
            )
            for link in email_links:
                await link_transaction_email(new_id, link["email_id"], link["role"], db_path=db_path)
            new_ids.append(new_id)

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "DELETE FROM transaction_emails WHERE transaction_id = ?", (transaction_id,)
            )
            await db.execute(
                "DELETE FROM transactions WHERE transaction_id = ?", (transaction_id,)
            )
            await db.commit()

        return {"success": True, "original_id": transaction_id, "new_transaction_ids": new_ids}
    except Exception as exc:
        return {"error": "Split failed", "detail": str(exc)}
