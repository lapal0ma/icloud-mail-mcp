import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_filter_stats, DB_PATH
from imap_client import fetch_new_emails

logger = logging.getLogger(__name__)
HKT = timezone(timedelta(hours=8))


async def _sync_job() -> None:
    logger.info("Mail sync started")
    try:
        stored = await fetch_new_emails()
        logger.info("Mail sync complete — %d email(s) stored", len(stored))
    except Exception as exc:
        logger.error("Mail sync failed: %s", exc, exc_info=True)


async def _filter_stats_job() -> None:
    try:
        stats = await get_filter_stats(days=1)
        if not stats:
            logger.info("Filter stats (today): no emails filtered")
            return
        summary = ", ".join(f"{r['reason']}={r['count']}" for r in stats)
        logger.info("Filter stats (today): %s", summary)
    except Exception as exc:
        logger.error("Filter stats job failed: %s", exc)


async def _complete_past_bookings_job() -> None:
    """Auto-transition confirmed bookings whose scheduled_at has passed to completed."""
    try:
        now = datetime.now(HKT).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            result = await db.execute(
                """UPDATE bookings SET status = 'completed'
                   WHERE status = 'confirmed' AND scheduled_at < ?""",
                (now,),
            )
            await db.commit()
            if result.rowcount:
                logger.info("Auto-completed %d past booking(s)", result.rowcount)
    except Exception as exc:
        logger.error("Auto-complete bookings job failed: %s", exc)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_sync_job, "interval", minutes=60, id="imap_sync")
    scheduler.add_job(_complete_past_bookings_job, "interval", minutes=60, id="complete_bookings")
    # Log filter stats once a day at midnight HKT
    scheduler.add_job(
        _filter_stats_job, "cron", hour=0, minute=0,
        timezone="Asia/Hong_Kong", id="filter_stats"
    )
    return scheduler


async def run() -> None:
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started — running initial sync")
    await _sync_job()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())
