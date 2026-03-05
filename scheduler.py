import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from imap_client import fetch_new_emails

logger = logging.getLogger(__name__)


async def _sync_job() -> None:
    logger.info("Mail sync started")
    try:
        stored = await fetch_new_emails()
        logger.info("Mail sync complete — %d email(s) stored", len(stored))
    except Exception as exc:
        logger.error("Mail sync failed: %s", exc, exc_info=True)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_sync_job, "interval", minutes=60, id="imap_sync")
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
