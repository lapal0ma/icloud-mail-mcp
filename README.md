# iCloud Mail MCP

An MCP server that connects to iCloud Mail, fetches emails, and exposes structured tools for reading transactions, bookings, and newsletter activities.

## Architecture

```
iCloud IMAP (imap.mail.me.com:993)
        │
        ▼
  imap_client.py  ──── sensitive filter ────► stored as [REDACTED]
        │
        ▼
  database.py (SQLite: icloud_mail.db)
        │
        ├── raw_emails
        ├── transactions
        ├── bookings
        ├── newsletter_activities
        └── unprocessed_queue
        │
        ▼
  tools/ (fetch, write, payment, booking, newsletter, sync)
        │
        ▼
  main.py (MCP stdio server + APScheduler, syncs every 60 min)
```

## Prerequisites

- Python 3.11+
- iCloud Mail IMAP access enabled: [appleid.apple.com](https://appleid.apple.com) → iCloud → Mail → enable
- An App-Specific Password (not your real iCloud password)

## Installation

```bash
git clone <repo-url>
cd icloud-mail-mcp-liz
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```
ICLOUD_EMAIL=your_apple_id@icloud.com
ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

To generate an App-Specific Password:
1. Go to [appleid.apple.com](https://appleid.apple.com)
2. Sign In → Security → App-Specific Passwords → Generate
3. Label it (e.g. `icloud-mail-mcp`) and copy the result

## Running

```bash
python main.py
```

On startup: creates DB tables, starts the 60-minute sync scheduler, runs an immediate sync, then listens on stdio for MCP tool calls.

## Register with OpenClaw

Add to your OpenClaw MCP config:

```yaml
mcpServers:
  icloud-mail:
    command: python
    args:
      - /path/to/icloud-mail-mcp-liz/main.py
    env:
      ICLOUD_EMAIL: your_apple_id@icloud.com
      ICLOUD_APP_PASSWORD: xxxx-xxxx-xxxx-xxxx
```

## Security Notes

- All data stays local — SQLite only, no external services.
- Sensitive emails (OTP, 2FA, password reset, security alerts) are detected before storage. Only sender, truncated subject, and timestamp are kept; body is replaced with `[REDACTED: sensitive content]`.
- The App-Specific Password can be revoked at any time from [appleid.apple.com](https://appleid.apple.com) without affecting your main account password.
- Never commit `.env` to version control — it is listed in `.gitignore`.
