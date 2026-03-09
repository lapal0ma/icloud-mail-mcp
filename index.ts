import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import * as path from "path";
import * as readline from "readline";
// @ts-ignore — jiti resolves node builtins at runtime; @types/node not installed
import * as fs from "fs";

// Read ICLOUD_MCP_PYTHON from a .env file
function readDotEnv(envPath: string): Record<string, string> {
  try {
    const content = fs.readFileSync(envPath, "utf8") as string;
    const result: Record<string, string> = {};
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq < 1) continue;
      result[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
    }
    return result;
  } catch {
    return {};
  }
}

// ---------------------------------------------------------------------------
// Minimal MCP JSON-RPC stdio client (no external deps)
// ---------------------------------------------------------------------------

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: unknown;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string };
}

class McpClient {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
  private nextId = 1;
  private ready = false;
  private queue: (() => void)[] = [];
  private logger: { info: (...a: unknown[]) => void; error: (...a: unknown[]) => void };

  constructor(logger: { info: (...a: unknown[]) => void; error: (...a: unknown[]) => void }) {
    this.logger = logger;
  }

  start(python: string, scriptPath: string, cwd: string): void {
    this.proc = spawn(python, [scriptPath], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
      cwd,
    });

    const rl = readline.createInterface({ input: this.proc.stdout! });
    rl.on("line", (line) => {
      line = line.trim();
      if (!line) return;
      try {
        const msg = JSON.parse(line) as JsonRpcResponse;
        const handler = this.pending.get(msg.id);
        if (!handler) return;
        this.pending.delete(msg.id);
        if (msg.error) handler.reject(new Error(msg.error.message));
        else handler.resolve(msg.result);
      } catch {
        // non-JSON line from server (e.g. log output) — ignore
      }
    });

    this.proc.stderr!.on("data", (d: Buffer) => {
      const text = d.toString().trim();
      if (text) this.logger.info(`[icloud-mail-mcp] ${text}`);
    });

    this.proc.on("error", (err: Error) => {
      this.logger.error(`[icloud-mail-mcp] failed to spawn process: ${err.message}`);
      this.ready = false;
      for (const h of this.pending.values()) h.reject(err);
      this.pending.clear();
    });

    this.proc.on("exit", (code) => {
      this.logger.error(`[icloud-mail-mcp] process exited (code ${code})`);
      this.ready = false;
      for (const h of this.pending.values()) h.reject(new Error("MCP process exited"));
      this.pending.clear();
    });
  }

  async initialize(): Promise<void> {
    await this.send("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "openclaw-plugin", version: "1.0.0" },
    });
    this.proc!.stdin!.write(
      JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n"
    );
    this.ready = true;
    for (const fn of this.queue) fn();
    this.queue = [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<string> {
    const result = (await this.send("tools/call", { name, arguments: args })) as {
      content: { type: string; text: string }[];
    };
    return result.content?.map((c) => c.text).join("\n") ?? "";
  }

  stop(): void {
    if (this.proc) {
      this.proc.stdin?.end();
      this.proc.kill();
      this.proc = null;
    }
  }

  private send(method: string, params: unknown): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const doSend = () => {
        const id = this.nextId++;
        const req: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };
        this.pending.set(id, { resolve, reject });
        this.proc!.stdin!.write(JSON.stringify(req) + "\n");
      };
      if (this.ready || method === "initialize") doSend();
      else this.queue.push(doSend);
    });
  }
}

// ---------------------------------------------------------------------------
// Static tool definitions (mirrors TOOLS list in main.py)
// ---------------------------------------------------------------------------

const TOOL_DEFS = [
  { name: "get_unclassified_emails", description: "Return unprocessed emails (processed=0)", inputSchema: { type: "object", properties: { limit: { type: "integer", default: 50 } } } },
  { name: "get_classified_emails", description: "Return emails by category within last N days", inputSchema: { type: "object", required: ["category"], properties: { category: { type: "string" }, days: { type: "integer", default: 7 } } } },
  { name: "get_email_detail", description: "Return full detail for a single email", inputSchema: { type: "object", required: ["email_id"], properties: { email_id: { type: "string" } } } },
  { name: "save_email_classification", description: "Set category and confidence on an email", inputSchema: { type: "object", required: ["email_id", "category", "confidence"], properties: { email_id: { type: "string" }, category: { type: "string" }, confidence: { type: "number" } } } },
  { name: "save_payment_transaction", description: "Save a payment transaction extracted from emails", inputSchema: { type: "object", required: ["email_ids", "amount", "currency", "merchant", "category", "occurred_at", "payment_method"], properties: { email_ids: { type: "array", items: { type: "string" } }, amount: { type: "number" }, currency: { type: "string" }, merchant: { type: "string" }, category: { type: "string" }, occurred_at: { type: "string" }, payment_method: { type: "string" }, reference_no: { type: "string" }, notes: { type: "string" } } } },
  { name: "save_booking", description: "Save an activity booking extracted from an email", inputSchema: { type: "object", required: ["email_id", "activity_name", "venue", "scheduled_at", "status"], properties: { email_id: { type: "string" }, activity_name: { type: "string" }, venue: { type: "string" }, scheduled_at: { type: "string" }, status: { type: "string" }, instructor: { type: "string" }, booking_reference: { type: "string" }, notes: { type: "string" } } } },
  { name: "save_newsletter_activities", description: "Save activities extracted from a newsletter email", inputSchema: { type: "object", required: ["email_id", "sender_org", "title", "newsletter_date"], properties: { email_id: { type: "string" }, sender_org: { type: "string" }, title: { type: "string" }, newsletter_date: { type: "string" }, date_start: { type: "string" }, date_end: { type: "string" }, location: { type: "string" }, description: { type: "string" }, url: { type: "string" } } } },
  { name: "get_recent_transactions", description: "Return transactions within last N days", inputSchema: { type: "object", properties: { days: { type: "integer", default: 30 }, category: { type: "string" } } } },
  { name: "search_transactions", description: "Search transactions by merchant or notes", inputSchema: { type: "object", required: ["query"], properties: { query: { type: "string" } } } },
  { name: "get_transaction_summary", description: "Return total spend per category", inputSchema: { type: "object", properties: { days: { type: "integer", default: 30 } } } },
  { name: "split_transaction", description: "Split one transaction into multiple", inputSchema: { type: "object", required: ["transaction_id", "split_into"], properties: { transaction_id: { type: "string" }, split_into: { type: "array", items: { type: "object" } } } } },
  { name: "get_upcoming_bookings", description: "Return bookings scheduled in the next N days", inputSchema: { type: "object", properties: { days: { type: "integer", default: 30 } } } },
  { name: "search_bookings", description: "Search bookings by activity name or venue", inputSchema: { type: "object", required: ["query"], properties: { query: { type: "string" } } } },
  { name: "get_booking_detail", description: "Return full detail for a single booking", inputSchema: { type: "object", required: ["booking_id"], properties: { booking_id: { type: "string" } } } },
  { name: "get_newsletter_activities", description: "Return newsletter activities within last N days", inputSchema: { type: "object", properties: { days: { type: "integer", default: 30 } } } },
  { name: "search_newsletter_activities", description: "Search newsletter activities by title, description, or org", inputSchema: { type: "object", required: ["query"], properties: { query: { type: "string" } } } },
  { name: "sync_now", description: "Trigger an immediate IMAP fetch", inputSchema: { type: "object", properties: {} } },
  { name: "get_sync_status", description: "Return sync status and email counts", inputSchema: { type: "object", properties: {} } },
  { name: "get_unprocessed_queue", description: "Return emails in the unprocessed queue", inputSchema: { type: "object", properties: { limit: { type: "integer", default: 20 } } } },
];

// ---------------------------------------------------------------------------
// Module-level singletons — shared across all registry instances
// ---------------------------------------------------------------------------

// jiti injects __dirname at runtime; suppress the type error
declare const __dirname: string;

const _pluginDir = __dirname;
const _dotEnv = readDotEnv(path.join(_pluginDir, ".env"));
const PYTHON =
  (globalThis as any).process?.env?.ICLOUD_MCP_PYTHON ??
  _dotEnv["ICLOUD_MCP_PYTHON"] ??
  "python";

// Singleton client and readiness promise — created once, shared by all register() calls
let _client: McpClient | null = null;
let _clientReady: Promise<void> | null = null;
let _resolveReady: (() => void) | null = null;

function getClientReady(): Promise<void> {
  if (!_clientReady) {
    _clientReady = new Promise<void>((resolve) => {
      _resolveReady = resolve;
    });
  }
  return _clientReady;
}

// ---------------------------------------------------------------------------
// Plugin entry point
// ---------------------------------------------------------------------------

let _serviceRegistered = false;

export default function register(api: any): void {
  const scriptPath = path.resolve(_pluginDir, "main.py");

  // Ensure singleton client exists (first call wins)
  if (!_client) {
    _client = new McpClient(api.logger);
  }
  const client = _client;

  // Register all 19 tools synchronously — execute() awaits client readiness
  api.logger.info(`[icloud-mail-mcp] register() called — registering ${TOOL_DEFS.length} tools synchronously`);
  for (const def of TOOL_DEFS) {
    const toolName = def.name;
    api.registerTool(
      {
        name: toolName,
        description: def.description,
        parameters: def.inputSchema,
        async execute(_id: string, params: Record<string, unknown>) {
          await getClientReady();
          const text = await client.callTool(toolName, params);
          return { content: [{ type: "text", text }] };
        },
      },
      { optional: true }
    );
  }

  // Service manages process lifecycle only — register once across all registry instances
  if (!_serviceRegistered) {
    _serviceRegistered = true;
    api.registerService({
      id: "icloud-mail-mcp-process",
      start: async () => {
        api.logger.info("[icloud-mail-mcp] Starting MCP server process...");
        client.start(PYTHON, scriptPath, _pluginDir);
        await client.initialize();
        api.logger.info("[icloud-mail-mcp] MCP client ready (19 tools available)");
        if (_resolveReady) {
          _resolveReady();
          _resolveReady = null;
        }
      },
      stop: async () => {
        api.logger.info("[icloud-mail-mcp] Stopping MCP server process...");
        client.stop();
        // Reset so next start() creates a fresh readiness promise
        _clientReady = null;
        _resolveReady = null;
        _client = null;
        _serviceRegistered = false;
      },
    });
  }
}
