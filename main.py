import asyncio
import logging
from datetime import datetime, timezone, timedelta

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json

from database import create_tables
from scheduler import create_scheduler
from imap_client import fetch_new_emails

from tools.fetch_tools import get_unclassified_emails, get_classified_emails, get_email_detail
from tools.write_tools import (
    save_email_classification,
    save_payment_transaction,
    save_booking,
    save_newsletter_activities,
)
from tools.payment_tools import (
    get_recent_transactions,
    search_transactions,
    get_transaction_summary,
    split_transaction,
)
from tools.booking_tools import get_upcoming_bookings, search_bookings, get_booking_detail
from tools.newsletter_tools import get_newsletter_activities, search_newsletter_activities
from tools.sync_tools import sync_now, get_sync_status, get_unprocessed_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Server("icloud-mail-mcp")

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(name="get_unclassified_emails", description="Return unprocessed emails (processed=0)", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}),
    Tool(name="get_classified_emails", description="Return emails by category within last N days", inputSchema={"type": "object", "required": ["category"], "properties": {"category": {"type": "string"}, "days": {"type": "integer", "default": 7}}}),
    Tool(name="get_email_detail", description="Return full detail for a single email", inputSchema={"type": "object", "required": ["email_id"], "properties": {"email_id": {"type": "string"}}}),
    Tool(name="save_email_classification", description="Set category and confidence on an email", inputSchema={"type": "object", "required": ["email_id", "category", "confidence"], "properties": {"email_id": {"type": "string"}, "category": {"type": "string"}, "confidence": {"type": "number"}}}),
    Tool(name="save_payment_transaction", description="Save a payment transaction extracted from emails", inputSchema={"type": "object", "required": ["email_ids", "amount", "currency", "merchant", "category", "occurred_at", "payment_method"], "properties": {"email_ids": {"type": "array", "items": {"type": "string"}}, "amount": {"type": "number"}, "currency": {"type": "string"}, "merchant": {"type": "string"}, "category": {"type": "string"}, "occurred_at": {"type": "string"}, "payment_method": {"type": "string"}, "reference_no": {"type": "string"}, "notes": {"type": "string"}}}),
    Tool(name="save_booking", description="Save an activity booking extracted from an email", inputSchema={"type": "object", "required": ["email_id", "activity_name", "venue", "scheduled_at", "status"], "properties": {"email_id": {"type": "string"}, "activity_name": {"type": "string"}, "venue": {"type": "string"}, "scheduled_at": {"type": "string"}, "status": {"type": "string"}, "instructor": {"type": "string"}, "booking_reference": {"type": "string"}, "notes": {"type": "string"}}}),
    Tool(name="save_newsletter_activities", description="Save activities extracted from a newsletter email", inputSchema={"type": "object", "required": ["email_id", "sender_org", "title", "newsletter_date"], "properties": {"email_id": {"type": "string"}, "sender_org": {"type": "string"}, "title": {"type": "string"}, "newsletter_date": {"type": "string"}, "date_start": {"type": "string"}, "date_end": {"type": "string"}, "location": {"type": "string"}, "description": {"type": "string"}, "url": {"type": "string"}}}),
    Tool(name="get_recent_transactions", description="Return transactions within last N days", inputSchema={"type": "object", "properties": {"days": {"type": "integer", "default": 30}, "category": {"type": "string"}}}),
    Tool(name="search_transactions", description="Search transactions by merchant or notes", inputSchema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}),
    Tool(name="get_transaction_summary", description="Return total spend per category", inputSchema={"type": "object", "properties": {"days": {"type": "integer", "default": 30}}}),
    Tool(name="split_transaction", description="Split one transaction into multiple", inputSchema={"type": "object", "required": ["transaction_id", "split_into"], "properties": {"transaction_id": {"type": "string"}, "split_into": {"type": "array", "items": {"type": "object"}}}}),
    Tool(name="get_upcoming_bookings", description="Return bookings scheduled in the next N days", inputSchema={"type": "object", "properties": {"days": {"type": "integer", "default": 30}}}),
    Tool(name="search_bookings", description="Search bookings by activity name or venue", inputSchema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}),
    Tool(name="get_booking_detail", description="Return full detail for a single booking", inputSchema={"type": "object", "required": ["booking_id"], "properties": {"booking_id": {"type": "string"}}}),
    Tool(name="get_newsletter_activities", description="Return newsletter activities within last N days", inputSchema={"type": "object", "properties": {"days": {"type": "integer", "default": 30}}}),
    Tool(name="search_newsletter_activities", description="Search newsletter activities by title, description, or org", inputSchema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}),
    Tool(name="sync_now", description="Trigger an immediate IMAP fetch", inputSchema={"type": "object", "properties": {}}),
    Tool(name="get_sync_status", description="Return sync status and email counts", inputSchema={"type": "object", "properties": {}}),
    Tool(name="get_unprocessed_queue", description="Return emails in the unprocessed queue", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 20}}}),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    result = await _dispatch(name, arguments)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


async def _dispatch(name: str, args: dict):  # noqa: PLR0911
    match name:
        case "get_unclassified_emails":
            return await get_unclassified_emails(**args)
        case "get_classified_emails":
            return await get_classified_emails(**args)
        case "get_email_detail":
            return await get_email_detail(**args)
        case "save_email_classification":
            await save_email_classification(**args)
            return {"success": True}
        case "save_payment_transaction":
            return await save_payment_transaction(**args)
        case "save_booking":
            return {"booking_id": await save_booking(**args)}
        case "save_newsletter_activities":
            return {"activity_id": await save_newsletter_activities(**args)}
        case "get_recent_transactions":
            return await get_recent_transactions(**args)
        case "search_transactions":
            return await search_transactions(**args)
        case "get_transaction_summary":
            return await get_transaction_summary(**args)
        case "split_transaction":
            return await split_transaction(**args)
        case "get_upcoming_bookings":
            return await get_upcoming_bookings(**args)
        case "search_bookings":
            return await search_bookings(**args)
        case "get_booking_detail":
            return await get_booking_detail(**args)
        case "get_newsletter_activities":
            return await get_newsletter_activities(**args)
        case "search_newsletter_activities":
            return await search_newsletter_activities(**args)
        case "sync_now":
            return await sync_now()
        case "get_sync_status":
            return await get_sync_status()
        case "get_unprocessed_queue":
            return await get_unprocessed_queue(**args)
        case _:
            return {"error": "Unknown tool", "detail": name}


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def _startup() -> None:
    await create_tables()
    logger.info("Database tables ready")
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started")
    HKT = timezone(timedelta(hours=8))
    first_of_month = datetime.now(HKT).replace(day=1).strftime("%d-%b-%Y")
    logger.info("Running initial sync from %s", first_of_month)
    stored = await fetch_new_emails(since_date=first_of_month)
    logger.info("Initial sync complete — %d email(s) stored", len(stored))


async def main() -> None:
    await _startup()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
