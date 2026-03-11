import aiosqlite
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH = "icloud_mail.db"
HKT = timezone(timedelta(hours=8))


def now_hkt() -> str:
    return datetime.now(HKT).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS raw_emails (
    id                  TEXT PRIMARY KEY,
    uid                 TEXT UNIQUE,
    sender              TEXT,
    subject             TEXT,
    body_text           TEXT,
    body_html           TEXT,
    received_at         TEXT,
    category            TEXT,
    category_confidence REAL,
    processed           INTEGER DEFAULT 0,
    filtered_reason     TEXT,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS filter_stats (
    id          TEXT PRIMARY KEY,
    date        TEXT NOT NULL,
    reason      TEXT NOT NULL,
    count       INTEGER DEFAULT 0,
    updated_at  TEXT,
    UNIQUE(date, reason)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  TEXT PRIMARY KEY,
    amount          REAL,
    currency        TEXT DEFAULT 'HKD',
    merchant        TEXT,
    category        TEXT,
    occurred_at     TEXT,
    payment_method  TEXT,
    reference_no    TEXT,
    confidence      REAL,
    notes           TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS transaction_emails (
    transaction_id  TEXT,
    email_id        TEXT,
    role            TEXT,
    PRIMARY KEY (transaction_id, email_id)
);

CREATE TABLE IF NOT EXISTS bookings (
    id                  TEXT PRIMARY KEY,
    email_id            TEXT,
    activity_name       TEXT,
    venue               TEXT,
    instructor          TEXT,
    scheduled_at        TEXT,
    booking_reference   TEXT,
    status              TEXT,
    notes               TEXT,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS newsletter_activities (
    id              TEXT PRIMARY KEY,
    email_id        TEXT,
    sender_org      TEXT,
    title           TEXT,
    date_start      TEXT,
    date_end        TEXT,
    location        TEXT,
    description     TEXT,
    url             TEXT,
    newsletter_date TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS unprocessed_queue (
    id          TEXT PRIMARY KEY,
    email_id    TEXT,
    reason      TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT
);
"""


async def create_tables(db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(CREATE_TABLES_SQL)
        await db.commit()
    await _migrate(db_path)


# Columns to add if missing: (table, column, definition)
_MIGRATIONS = [
    ("raw_emails", "filtered_reason", "TEXT"),
]


async def _migrate(db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        for table, column, definition in _MIGRATIONS:
            async with db.execute(f"PRAGMA table_info({table})") as cur:
                cols = {row[1] for row in await cur.fetchall()}
            if column not in cols:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                await db.commit()


# ---------------------------------------------------------------------------
# raw_emails
# ---------------------------------------------------------------------------

async def insert_raw_email(
    uid: str,
    sender: str,
    subject: str,
    body_text: str,
    body_html: str,
    received_at: str,
    filtered_reason: Optional[str] = None,
    db_path: str = DB_PATH,
) -> tuple[str, bool]:
    """Returns (email_id, is_new). is_new=False means the uid already existed (INSERT OR IGNORE skipped)."""
    email_id = new_id()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO raw_emails
               (id, uid, sender, subject, body_text, body_html, received_at,
                processed, filtered_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (email_id, uid, sender, subject, body_text, body_html, received_at,
             filtered_reason, now_hkt()),
        )
        await db.commit()
        if cursor.rowcount == 0:
            # Already exists — fetch the real id
            async with db.execute("SELECT id FROM raw_emails WHERE uid = ?", (uid,)) as cur:
                row = await cur.fetchone()
                email_id = row[0] if row else email_id
            return email_id, False
    return email_id, True


async def get_raw_email(email_id: str, db_path: str = DB_PATH) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM raw_emails WHERE id = ?", (email_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_email_category(
    email_id: str,
    category: str,
    confidence: float,
    processed: int,
    db_path: str = DB_PATH,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """UPDATE raw_emails
               SET category = ?, category_confidence = ?, processed = ?
               WHERE id = ?""",
            (category, confidence, processed, email_id),
        )
        await db.commit()


async def get_unclassified_emails(db_path: str = DB_PATH) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM raw_emails WHERE processed = 0 ORDER BY received_at"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------

async def insert_transaction(
    amount: float,
    merchant: str,
    occurred_at: str,
    currency: str = "HKD",
    category: Optional[str] = None,
    payment_method: Optional[str] = None,
    reference_no: Optional[str] = None,
    confidence: Optional[float] = None,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> str:
    txn_id = new_id()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO transactions
               (transaction_id, amount, currency, merchant, category,
                occurred_at, payment_method, reference_no, confidence, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (txn_id, amount, currency, merchant, category,
             occurred_at, payment_method, reference_no, confidence, notes, now_hkt()),
        )
        await db.commit()
    return txn_id


async def get_transaction(txn_id: str, db_path: str = DB_PATH) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM transactions WHERE transaction_id = ?", (txn_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_transactions(
    limit: int = 50, offset: int = 0, db_path: str = DB_PATH
) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM transactions ORDER BY occurred_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def update_transaction(txn_id: str, db_path: str = DB_PATH, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE transactions SET {cols} WHERE transaction_id = ?",
            (*fields.values(), txn_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# transaction_emails
# ---------------------------------------------------------------------------

async def link_transaction_email(
    transaction_id: str, email_id: str, role: str, db_path: str = DB_PATH
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR IGNORE INTO transaction_emails (transaction_id, email_id, role)
               VALUES (?, ?, ?)""",
            (transaction_id, email_id, role),
        )
        await db.commit()


async def get_emails_for_transaction(
    transaction_id: str, db_path: str = DB_PATH
) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM transaction_emails WHERE transaction_id = ?", (transaction_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# bookings
# ---------------------------------------------------------------------------

async def insert_booking(
    email_id: str,
    activity_name: str,
    scheduled_at: str,
    venue: Optional[str] = None,
    instructor: Optional[str] = None,
    booking_reference: Optional[str] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> str:
    booking_id = new_id()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO bookings
               (id, email_id, activity_name, venue, instructor,
                scheduled_at, booking_reference, status, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (booking_id, email_id, activity_name, venue, instructor,
             scheduled_at, booking_reference, status, notes, now_hkt()),
        )
        await db.commit()
    return booking_id


async def get_booking(booking_id: str, db_path: str = DB_PATH) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_bookings(
    limit: int = 50, offset: int = 0, db_path: str = DB_PATH
) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bookings ORDER BY scheduled_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def update_booking_status(
    booking_id: str,
    status: str,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        if notes is not None:
            await db.execute(
                "UPDATE bookings SET status = ?, notes = ? WHERE id = ?",
                (status, notes, booking_id),
            )
        else:
            await db.execute(
                "UPDATE bookings SET status = ? WHERE id = ?",
                (status, booking_id),
            )
        await db.commit()


async def find_booking_by_reference(
    booking_reference: str, db_path: str = DB_PATH
) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bookings WHERE booking_reference = ? ORDER BY created_at DESC LIMIT 1",
            (booking_reference,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ---------------------------------------------------------------------------
# newsletter_activities
# ---------------------------------------------------------------------------

async def insert_newsletter_activity(
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
    activity_id = new_id()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO newsletter_activities
               (id, email_id, sender_org, title, date_start, date_end,
                location, description, url, newsletter_date, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (activity_id, email_id, sender_org, title, date_start, date_end,
             location, description, url, newsletter_date, now_hkt()),
        )
        await db.commit()
    return activity_id


async def get_newsletter_activity(
    activity_id: str, db_path: str = DB_PATH
) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM newsletter_activities WHERE id = ?", (activity_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_newsletter_activities(
    limit: int = 50, offset: int = 0, db_path: str = DB_PATH
) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM newsletter_activities
               ORDER BY newsletter_date DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# unprocessed_queue
# ---------------------------------------------------------------------------

async def enqueue_unprocessed(
    email_id: str, reason: str, db_path: str = DB_PATH
) -> str:
    queue_id = new_id()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR IGNORE INTO unprocessed_queue (id, email_id, reason, created_at)
               VALUES (?, ?, ?, ?)""",
            (queue_id, email_id, reason, now_hkt()),
        )
        await db.commit()
    return queue_id


async def dequeue_unprocessed(queue_id: str, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM unprocessed_queue WHERE id = ?", (queue_id,))
        await db.commit()


async def list_unprocessed_queue(db_path: str = DB_PATH) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM unprocessed_queue ORDER BY created_at"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# filter_stats
# ---------------------------------------------------------------------------

async def bump_filter_stat(reason: str, date: str, db_path: str = DB_PATH) -> None:
    """Increment the daily counter for a filter reason (upsert)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO filter_stats (id, date, reason, count, updated_at)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(date, reason) DO UPDATE SET
                 count = count + 1,
                 updated_at = excluded.updated_at""",
            (new_id(), date, reason, now_hkt()),
        )
        await db.commit()


async def get_filter_stats(days: int = 7, db_path: str = DB_PATH) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT date, reason, count FROM filter_stats
               WHERE date >= date('now', ?)
               ORDER BY date DESC, count DESC""",
            (f"-{days} days",),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# sync_state
# ---------------------------------------------------------------------------

async def get_sync_state(key: str, db_path: str = DB_PATH) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_sync_state(key: str, value: str, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, value, now_hkt()),
        )
        await db.commit()
