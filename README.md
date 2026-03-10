# iCloud Mail MCP

An OpenClaw plugin that bridges a Python MCP server to native agent tools. Connects to iCloud Mail via IMAP, stores structured data locally, and exposes 19 tools for email classification, transactions, bookings, and newsletters.

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
        │
        ▼
  index.ts (OpenClaw plugin bridge — spawns main.py, registers 19 tools)
        │
        ▼
  OpenClaw agents (main + email)
```

## Prerequisites

- Python 3.11+ (conda env `datus` recommended)
- iCloud Mail IMAP access enabled: [appleid.apple.com](https://appleid.apple.com) → iCloud → Mail → enable
- An App-Specific Password (not your real iCloud password)

## Installation

```bash
git clone https://github.com/lapal0ma/icloud-mail-mcp
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
ICLOUD_MCP_PYTHON=/path/to/conda/envs/datus/bin/python
```

`ICLOUD_MCP_PYTHON` tells the OpenClaw plugin which Python binary to use. If omitted, falls back to `python` on PATH.

To generate an App-Specific Password:
1. Go to [appleid.apple.com](https://appleid.apple.com)
2. Sign In → Security → App-Specific Passwords → Generate
3. Label it (e.g. `icloud-mail-mcp`) and copy the result

## Running standalone

```bash
python main.py
```

On startup: creates DB tables, starts the 60-minute sync scheduler, runs an immediate sync from the first day of the current month, then listens on stdio for MCP tool calls.

## OpenClaw Plugin Setup

This project is an OpenClaw plugin — no separate MCP config needed. OpenClaw loads `index.ts` directly via jiti (no build step).

### 1. Register the plugin path

In `~/.openclaw/openclaw.json`:

```json
"plugins": {
  "allow": ["icloud-mail-mcp-liz"],
  "load": {
    "paths": ["/path/to/icloud-mail-mcp-liz"]
  },
  "entries": {
    "icloud-mail-mcp-liz": { "enabled": true }
  }
}
```

### 2. Enable tools for each agent

```json
"agents": {
  "list": [
    {
      "id": "main",
      "tools": { "alsoAllow": ["group:plugins"] }
    },
    {
      "id": "email",
      "name": "Email Agent",
      "workspace": "/path/to/separate/workspace",
      "model": { "primary": "your-model" },
      "tools": { "alsoAllow": ["icloud-mail-mcp-liz"] }
    }
  ]
}
```

### 3. Restart gateway

```bash
openclaw gateway restart
```

## Security Notes

- All data stays local — SQLite only, no external services.
- Sensitive emails (OTP, 2FA, password reset, security alerts) are detected before storage. Only sender, truncated subject, and timestamp are kept; body is replaced with `[REDACTED: sensitive content]`.
- The App-Specific Password can be revoked at any time from [appleid.apple.com](https://appleid.apple.com) without affecting your main account password.
- Never commit `.env` to version control — it is listed in `.gitignore`.

---

## Development Log

### 2026-03-09

### Problem: IMAP fetch returned empty sender/subject
**Reason:** iCloud IMAP returns empty data when fetching with `RFC822`. The standard fetch command doesn't work on iCloud's server.
**Revision:** Switched to `BODY.PEEK[]` fetch command. Also fixed `bytearray` vs `bytes` type mismatch — `aioimaplib` returns `bytearray` at `msg_data[1]`, requiring explicit `bytes(raw)` conversion.

### Problem: `spawn python ENOENT` — Python process failed to start
**Reason:** OpenClaw gateway doesn't inherit shell PATH or conda environment. The `ICLOUD_MCP_PYTHON` env var wasn't being read because the gateway's process env doesn't load `.env` files.
**Revision:** Added `.env` file parsing directly in `index.ts` using `import * as fs from "fs"` with `// @ts-ignore`. Added `ICLOUD_MCP_PYTHON` key to `.env.example`.

### Problem: `sqlite3.OperationalError: unable to open database file`
**Reason:** Python process was spawned with the gateway's working directory, so the relative path `icloud_mail.db` resolved to the wrong location.
**Revision:** Added `cwd: _pluginDir` to the `spawn()` call so the Python process always runs from the plugin directory.

### Problem: `__dirname` was empty string at runtime
**Reason:** jiti injects `__dirname` as a module-local variable, not on `globalThis`. Accessing it via `globalThis.__dirname` returned `""`.
**Revision:** Added `declare const __dirname: string` to use the jiti-injected value directly.

### 2026-03-10

### Problem: Email agent (non-default workspace) had zero plugin tools
**Reason:** OpenClaw caches the plugin registry by workspace path. Non-default agents get a fresh registry where `service.start()` never runs — tools registered inside `start()` never appear.
**Revision:** Moved all 19 `registerTool()` calls to the synchronous `register(api)` body using a static `TOOL_DEFS` array. Each `execute()` awaits a module-level `_clientReady` promise that resolves once `start()` finishes initialization.

### Problem: `_serviceRegistered` guard silently skipped service registration for email agent
**Reason:** The guard called `api.registerService()` only once — but each agent's registry gets its own `api`. The email agent's `api` never got `registerService`, so `start()` was never called for it.
**Revision:** Removed the guard. `registerService` is called on every `api`. Spawn is guarded by `if (_client) return` inside `start()` instead.

### Problem: `stop()` from any registry killed the shared MCP process
**Reason:** Any registry calling `stop()` would `_client.stop()` and null out the singleton, breaking all other agents.
**Revision:** Added `_registryCount` reference counter — only kill the process when it reaches zero.

### Problem: All tool calls hung forever — `_clientReady` race condition (root cause)
**Reason:** `_clientReady` was created lazily in `getClientReady()`. If `start()` completed before any `execute()` called `getClientReady()`, `_resolveReady` was still `null` when `_resolveReady!()` fired — a no-op. Every subsequent tool call awaited a promise that would never resolve.
**Revision:** Create `_clientReady = new Promise(...)` at the top of `start()` before spawning, so `_resolveReady` is always set before it's called.

### Problem: Stale `_client` after MCP process crash prevented respawn
**Reason:** `_client` stayed non-null after the Python process exited. Next `start()` hit `if (_client) return` and skipped respawning.
**Revision:** `proc.on("exit")` handler resets `_client`, `_clientReady`, and `_resolveReady` to `null`.

### Problem: main.py blocked stdio during startup — `initialize` handshake timed out
**Reason:** Initial IMAP fetch (~70 s, 236 emails) ran before `stdio_server()` opened, blocking the MCP handshake.
**Revision:** Moved `asyncio.create_task(_background_sync())` inside `main()` after `stdio_server()` opens. Server is ready immediately; sync runs in the background.
