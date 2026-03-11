"""
email_filter.py — applies filter_rules.json before emails reach the classification agent.

Returns a (reason: str | None) where None means "pass through".
processed value for filtered emails: -2
"""
import fnmatch
import json
import logging
import re
from pathlib import Path
from typing import Optional

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).parent / "filter_rules.json"


def _load_rules() -> dict:
    try:
        return json.loads(_RULES_PATH.read_text())
    except Exception as exc:
        logger.warning("Could not load filter_rules.json: %s", exc)
        return {}


def _extract_email_address(sender: str) -> str:
    """Pull bare address from 'Display Name <addr@domain>' or return as-is."""
    m = re.search(r"<([^>]+)>", sender)
    return m.group(1).lower() if m else sender.lower().strip()


def _local_part(addr: str) -> str:
    return addr.split("@")[0] if "@" in addr else addr


def _domain(addr: str) -> str:
    return addr.split("@")[1] if "@" in addr else ""


# ---------------------------------------------------------------------------
# Individual rule checkers
# ---------------------------------------------------------------------------

def _check_mailing_list(addr: str, rules: dict) -> Optional[str]:
    cfg = rules.get("mailing_lists", {})
    if not cfg.get("enabled"):
        return None
    for pattern in cfg.get("sender_patterns", []):
        if pattern.startswith("@*."):
            # domain glob: @*.apache.org matches anything.apache.org
            domain_glob = pattern[1:]  # *.apache.org
            if fnmatch.fnmatch(_domain(addr), domain_glob):
                return cfg["reason"]
        elif pattern.startswith("@"):
            if _domain(addr).startswith(pattern[1:]):
                return cfg["reason"]
        else:
            if pattern in addr:
                return cfg["reason"]
    return None


def _check_sender_pattern(addr: str, rules: dict) -> Optional[str]:
    cfg = rules.get("sender_patterns", {})
    if not cfg.get("enabled"):
        return None
    domain = _domain(addr)
    for pattern in cfg.get("domain_allowlist", []):
        if fnmatch.fnmatch(domain, pattern):
            return None
    local = _local_part(addr)
    for prefix in cfg.get("local_part_prefixes", []):
        if local == prefix or local.startswith(prefix + ".") or local.startswith(prefix + "-"):
            return cfg["reason"]
    for suffix in cfg.get("local_part_suffixes", []):
        if local.endswith(suffix):
            return cfg["reason"]
    return None


def _check_subject_urgency(subject: str, rules: dict) -> Optional[str]:
    cfg = rules.get("subject_urgency", {})
    if not cfg.get("enabled"):
        return None
    subject_lower = subject.lower()
    for kw in cfg.get("keywords", []):
        if kw.lower() in subject_lower:
            return cfg["reason"]
    return None


async def _check_high_freq_promo(addr: str, rules: dict, db_path: str) -> Optional[str]:
    cfg = rules.get("high_freq_promo", {})
    if not cfg.get("enabled"):
        return None
    known = [s.lower() for s in cfg.get("senders", [])]
    if addr not in known:
        return None
    threshold = cfg.get("threshold_per_week", 1)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT COUNT(*) FROM raw_emails
               WHERE lower(sender) LIKE ?
               AND received_at >= datetime('now', '-7 days')""",
            (f"%{addr}%",),
        ) as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0
    if count >= threshold:
        return cfg["reason"]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def should_filter(
    sender: str,
    subject: str,
    db_path: str = DB_PATH,
) -> Optional[str]:
    """
    Returns a filter reason string if the email should be filtered out,
    or None if it should pass through to the agent.
    """
    rules = _load_rules()
    addr = _extract_email_address(sender)

    reason = _check_mailing_list(addr, rules)
    if reason:
        return reason

    reason = _check_sender_pattern(addr, rules)
    if reason:
        return reason

    reason = _check_subject_urgency(subject, rules)
    if reason:
        return reason

    reason = await _check_high_freq_promo(addr, rules, db_path)
    if reason:
        return reason

    return None
