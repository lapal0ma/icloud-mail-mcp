---
name: icloud-mail
description: |
  iCloud Mail tools for reading emails, saving transactions, bookings, and newsletter activities.
  Activate when the user asks about their emails, bills, payments, yoga/fitness bookings, or newsletters.
---

# iCloud Mail Tools

All tools are optional and must be enabled via `tools.allow: ["icloud-mail-mcp-liz"]` in agent config.

---

## Sync

### `sync_now`
Trigger an immediate IMAP fetch from iCloud.
```json
{}
```
Returns: `{ synced_count, duration_seconds }`

### `get_sync_status`
Return sync status and email counts.
```json
{}
```
Returns: `{ last_sync_at, total_emails, unclassified_count, sensitive_filtered_count, unprocessed_queue_count }`

### `get_unprocessed_queue`
Return emails that failed classification (e.g. low confidence).
```json
{ "limit": 20 }
```

---

## Reading Emails

### `get_unclassified_emails`
Return emails not yet processed (processed=0). Never returns sensitive/redacted emails.
```json
{ "limit": 50 }
```
Returns: list of `{ id, sender, subject, body_text, received_at }`

### `get_classified_emails`
Return emails of a given category within the last N days.
```json
{ "category": "transaction", "days": 7 }
```
Categories: `transaction`, `booking`, `newsletter`, `promotional`, `security_sensitive`

### `get_email_detail`
Return full detail for a single email including `body_html`. Never returns sensitive emails.
```json
{ "email_id": "uuid" }
```

---

## Classifying & Writing

### `save_email_classification`
Set category and confidence on an email. If confidence < 0.7, email is queued for review.
```json
{ "email_id": "uuid", "category": "promotional", "confidence": 0.95 }
```

### `save_payment_transaction`
Extract and save a payment transaction from one or more emails. Runs deduplication automatically.
```json
{
  "email_ids": ["uuid"],
  "amount": 450.0,
  "currency": "HKD",
  "merchant": "Aeon",
  "category": "groceries",
  "occurred_at": "2026-03-01T14:30:00+08:00",
  "payment_method": "credit_card",
  "reference_no": "TXN123",
  "notes": "Weekly groceries"
}
```
Returns: `{ transaction_id, deduplicated, merged_with }`

### `save_booking`
Save a fitness/activity booking extracted from an email.
```json
{
  "email_id": "uuid",
  "activity_name": "Yoga Flow",
  "venue": "Pure Yoga",
  "scheduled_at": "2026-03-10T09:00:00+08:00",
  "status": "confirmed",
  "instructor": "Sarah",
  "booking_reference": "BK001",
  "notes": ""
}
```

### `save_newsletter_activities`
Save an event/activity extracted from a newsletter email.
```json
{
  "email_id": "uuid",
  "sender_org": "YMCA Hong Kong",
  "title": "Spring Swimming Workshop",
  "newsletter_date": "2026-03-01",
  "date_start": "2026-03-15",
  "date_end": "2026-03-15",
  "location": "YMCA Tsim Sha Tsui",
  "description": "Beginner swimming workshop",
  "url": "https://ymca.org.hk/events/123"
}
```

---

## Transactions

### `get_recent_transactions`
Return transactions within the last N days, optionally filtered by category.
```json
{ "days": 30, "category": "dining" }
```

### `search_transactions`
Search transactions by merchant name or notes.
```json
{ "query": "aeon" }
```

### `get_transaction_summary`
Return total spend per category for the last N days.
```json
{ "days": 30 }
```
Returns: list of `{ category, currency, count, total }`

### `split_transaction`
Split one transaction into multiple (e.g. shared bill). Each item needs `amount`, `merchant`, `category`.
```json
{
  "transaction_id": "uuid",
  "split_into": [
    { "amount": 200.0, "merchant": "Aeon", "category": "groceries" },
    { "amount": 250.0, "merchant": "Aeon", "category": "household" }
  ]
}
```

---

## Bookings

### `get_upcoming_bookings`
Return bookings scheduled in the next N days.
```json
{ "days": 30 }
```

### `search_bookings`
Search bookings by activity name or venue.
```json
{ "query": "yoga" }
```

### `get_booking_detail`
Return full detail for a single booking.
```json
{ "booking_id": "uuid" }
```

---

## Newsletter Activities

### `get_newsletter_activities`
Return newsletter activities from the last N days.
```json
{ "days": 30 }
```

### `search_newsletter_activities`
Search newsletter activities by title, description, or organisation name.
```json
{ "query": "swimming" }
```

---

## Rules

- **Always use MCP tools** — never access the SQLite database directly via raw SQL or `exec`. All reads and writes must go through the MCP tool interface (`get_unclassified_emails`, `save_email_classification`, `save_payment_transaction`, etc.). Direct DB access bypasses deduplication, validation, and pipeline logic.

---

## Typical Workflows

**Process unclassified emails:**
1. `get_unclassified_emails` — fetch up to 50 unprocessed emails
2. For each email, read `sender`, `subject`, `body_text` and decide category
3. Call the appropriate save tool (`save_payment_transaction`, `save_booking`, `save_newsletter_activities`)
   or `save_email_classification` with category `promotional` / `other`

**Monthly spending summary:**
1. `get_transaction_summary` with `days: 30`
2. Optionally `get_recent_transactions` with a specific category for detail

**Check upcoming classes:**
1. `get_upcoming_bookings` with `days: 14`
