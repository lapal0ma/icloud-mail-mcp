import aiosqlite
from typing import Optional

from database import (
    DB_PATH,
    update_email_category,
    enqueue_unprocessed,
    insert_transaction,
    link_transaction_email,
    insert_booking,
    insert_newsletter_activity,
)
from deduplicator import check_duplicate

_LOW_CONFIDENCE_THRESHOLD = 0.7


async def save_email_classification(
    email_id: str,
    category: str,
    confidence: float,
    db_path: str = DB_PATH,
) -> None:
    """
    Set category + confidence on a raw_email and mark processed=1.
    If confidence < 0.7, also enqueue into unprocessed_queue.
    """
    await update_email_category(email_id, category, confidence, processed=1, db_path=db_path)
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        await enqueue_unprocessed(email_id, reason="low_confidence", db_path=db_path)


async def save_payment_transaction(
    email_ids: list[str],
    amount: float,
    currency: str,
    merchant: str,
    category: str,
    occurred_at: str,
    payment_method: str,
    reference_no: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> dict:
    """
    Deduplicate, insert transaction + links, mark emails processed=2.
    Returns {transaction_id, deduplicated, merged_with}.
    """
    dup = await check_duplicate(amount, merchant, occurred_at, db_path=db_path)

    if dup["is_duplicate"]:
        transaction_id = dup["matched_transaction_id"]
        deduplicated = True
    else:
        transaction_id = await insert_transaction(
            amount=amount,
            merchant=merchant,
            occurred_at=occurred_at,
            currency=currency,
            category=category,
            payment_method=payment_method,
            reference_no=reference_no,
            notes=notes,
            db_path=db_path,
        )
        deduplicated = False

    async with aiosqlite.connect(db_path) as db:
        for email_id in email_ids:
            await db.execute(
                """INSERT OR IGNORE INTO transaction_emails (transaction_id, email_id, role)
                   VALUES (?, ?, 'source')""",
                (transaction_id, email_id),
            )
        await db.execute(
            "UPDATE raw_emails SET processed = 2 WHERE id IN ({})".format(
                ",".join("?" * len(email_ids))
            ),
            email_ids,
        )
        await db.commit()

    return {
        "transaction_id": transaction_id,
        "deduplicated": deduplicated,
        "merged_with": transaction_id if deduplicated else None,
    }


async def save_booking(
    email_id: str,
    activity_name: str,
    venue: str,
    scheduled_at: str,
    status: str,
    instructor: Optional[str] = None,
    booking_reference: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> str:
    """Insert booking and mark email processed=2. Returns booking id."""
    booking_id = await insert_booking(
        email_id=email_id,
        activity_name=activity_name,
        venue=venue,
        scheduled_at=scheduled_at,
        status=status,
        instructor=instructor,
        booking_reference=booking_reference,
        notes=notes,
        db_path=db_path,
    )
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE raw_emails SET processed = 2 WHERE id = ?", (email_id,))
        await db.commit()
    return booking_id


async def save_newsletter_activities(
    email_id: str,
    sender_org: str,
    title: str,
    newsletter_date: str,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    url: Optional[str] = None,
    db_path: str = DB_PATH,
) -> str:
    """Insert newsletter activity and mark email processed=2. Returns activity id."""
    activity_id = await insert_newsletter_activity(
        email_id=email_id,
        sender_org=sender_org,
        title=title,
        newsletter_date=newsletter_date,
        date_start=date_start,
        date_end=date_end,
        location=location,
        description=description,
        url=url,
        db_path=db_path,
    )
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE raw_emails SET processed = 2 WHERE id = ?", (email_id,))
        await db.commit()
    return activity_id
