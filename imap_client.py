import asyncio
import email
import logging
import re
from datetime import datetime, timezone, timedelta
from email.header import decode_header
from typing import Optional

import aioimaplib
from bs4 import BeautifulSoup

from config import ICLOUD_EMAIL, ICLOUD_APP_PASSWORD
from database import insert_raw_email, update_email_category

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993
HKT = timezone(timedelta(hours=8))

SENSITIVE_KEYWORDS = [
    "验证码", "otp", "one-time password", "verification code",
    "verify your email", "confirm your email", "登录提醒",
    "new sign-in", "new login", "reset your password",
    "forgot password", "两步验证", "2fa", "two-factor",
    "security alert", "安全提醒",
]


def _is_sensitive(subject: str, body_preview: str) -> bool:
    haystack = (subject + " " + body_preview[:500]).lower()
    return any(kw in haystack for kw in SENSITIVE_KEYWORDS)


def _decode_header_value(raw: str) -> str:
    parts = decode_header(raw or "")
    decoded = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return "".join(decoded)


def _html_to_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        # Fallback: strip tags with regex
        return re.sub(r"<[^>]+>", " ", html).strip()


def _parse_message(raw_bytes: bytes) -> dict:
    msg = email.message_from_bytes(raw_bytes)

    subject = _decode_header_value(msg.get("Subject", ""))
    sender = _decode_header_value(msg.get("From", ""))
    date_str = msg.get("Date", "")

    try:
        received_at = email.utils.parsedate_to_datetime(date_str).astimezone(HKT).isoformat()
    except Exception:
        received_at = datetime.now(HKT).isoformat()

    body_text = ""
    body_html = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                body_text = payload.decode(charset, errors="replace") if payload else ""
            elif ct == "text/html" and not body_html:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                body_html = payload.decode(charset, errors="replace") if payload else ""
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        content = payload.decode(charset, errors="replace") if payload else ""
        if msg.get_content_type() == "text/html":
            body_html = content
        else:
            body_text = content

    # Derive plain text from HTML if no plain part
    if not body_text and body_html:
        body_text = _html_to_text(body_html)

    return {
        "subject": subject,
        "sender": sender,
        "received_at": received_at,
        "body_text": body_text,
        "body_html": body_html,
    }


async def _connect_with_retry(max_attempts: int = 3) -> aioimaplib.IMAP4_SSL:
    delay = 2.0
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            client = aioimaplib.IMAP4_SSL(host=IMAP_HOST, port=IMAP_PORT)
            await client.wait_hello_from_server()
            await client.login(ICLOUD_EMAIL, ICLOUD_APP_PASSWORD)
            logger.info("IMAP login successful on attempt %d", attempt)
            return client
        except Exception as exc:
            last_exc = exc
            logger.warning("IMAP connect attempt %d failed: %s", attempt, exc)
            if attempt < max_attempts:
                await asyncio.sleep(delay)
                delay *= 2
    raise ConnectionError(f"IMAP connection failed after {max_attempts} attempts") from last_exc


async def fetch_new_emails(
    mailbox: str = "INBOX",
    since_days: int = 7,
    since_date: Optional[str] = None,
    db_path: str = "icloud_mail.db",
) -> list[str]:
    """
    Fetch emails from iCloud and persist them via database.py.
    Pass since_date (DD-Mon-YYYY) to override the since_days rolling window.
    Returns list of stored email IDs.
    """
    client = await _connect_with_retry()
    stored_ids: list[str] = []

    try:
        await client.select(mailbox)

        if since_date is None:
            since_date = (datetime.now(HKT) - timedelta(days=since_days)).strftime("%d-%b-%Y")
        _, data = await client.search(f'SINCE {since_date}')
        uids = data[0].split() if data and data[0] else []
        logger.info("Found %d messages since %s", len(uids), since_date)

        for uid_bytes in uids:
            uid = uid_bytes.decode() if isinstance(uid_bytes, bytes) else uid_bytes
            try:
                _, msg_data = await client.fetch(uid, "(BODY.PEEK[])")
                # aioimaplib returns [b'<seq> FETCH (BODY[] {size}', bytearray(<message>), b')', ...]
                if not msg_data or len(msg_data) < 2:
                    continue
                raw = msg_data[1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                raw = bytes(raw)

                parsed = _parse_message(raw)

                if _is_sensitive(parsed["subject"], parsed["body_text"]):
                    email_id = await insert_raw_email(
                        uid=uid,
                        sender=parsed["sender"],
                        subject=parsed["subject"][:10] + "***",
                        body_text="[REDACTED: sensitive content]",
                        body_html="[REDACTED: sensitive content]",
                        received_at=parsed["received_at"],
                        db_path=db_path,
                    )
                    await update_email_category(
                        email_id=email_id,
                        category="security_sensitive",
                        confidence=1.0,
                        processed=-1,
                        db_path=db_path,
                    )
                    logger.info("Stored sensitive email uid=%s as redacted", uid)
                else:
                    email_id = await insert_raw_email(
                        uid=uid,
                        sender=parsed["sender"],
                        subject=parsed["subject"],
                        body_text=parsed["body_text"],
                        body_html=parsed["body_html"],
                        received_at=parsed["received_at"],
                        db_path=db_path,
                    )
                    logger.info("Stored email uid=%s id=%s", uid, email_id)

                stored_ids.append(email_id)

            except Exception as exc:
                logger.error("Failed to process uid=%s: %s", uid, exc)

    finally:
        try:
            await client.logout()
        except Exception:
            pass

    return stored_ids
