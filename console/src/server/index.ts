// The console's local server: node `http` only (no express), serving the built
// SPA statically and exposing the API the SPA consumes:
//
//   GET  /health                     the healthcheck contract (engine version)
//   GET  /api/traces                 list trace-*.jsonl under the trace dir
//   GET  /api/trace?path=            one trace, derived into turns
//   GET  /api/feed?path=&cursor=     tail deltas (append-only polling)
//   POST /api/verify                 `belay verify --json` over one trace/turn
//   POST /api/replay                 `belay verify --turn N --json` (N1)
//   POST /api/events                 one click/expand record → console-events.jsonl
//
// Every verdict travels in the engine's document; this server computes none.

import { appendFile, readFile, readdir, stat } from "node:fs/promises";
import { createServer as httpCreateServer } from "node:http";
import type { IncomingMessage, Server, ServerResponse } from "node:http";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { probeEngineVersion, runVerifyJson } from "./engine.js";
import { createTailState, readTail } from "./tail.js";
import type { TailState } from "./tail.js";
import { deriveTurns } from "./trace.js";

export interface ServerConfig {
  traceDir?: string;
  eventsFile?: string;
  distDir?: string;
  env?: NodeJS.ProcessEnv;
  now?: () => Date;
  log?: (line: string) => void;
  /** The /health engine-version probe; injected for tests, python-based by default. */
  engineVersion?: () => Promise<string | null>;
}

export interface TraceListing {
  name: string;
  path: string;
  size: number;
  mtime: string;
  turns: number;
}

const TRACE_PREFIX = "trace-";
const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json; charset=utf-8",
  ".ico": "image/x-icon",
  ".map": "application/json; charset=utf-8",
  ".woff2": "font/woff2",
};

export function createServer(config: ServerConfig = {}): Server {
  const traceDir = config.traceDir ?? process.env.BELAY_CONSOLE_TRACE_DIR ?? path.join(homedir(), ".belay", "traces");
  const eventsFile =
    config.eventsFile ?? process.env.BELAY_CONSOLE_EVENTS ?? path.join(homedir(), ".belay", "console-events.jsonl");
  const distDir = config.distDir ?? fileURLToPath(new URL("../../dist", import.meta.url));
  const now = config.now ?? (() => new Date());
  const log = config.log ?? ((line: string) => console.error(`[belay-console] ${line}`));
  const env = config.env ?? process.env;
  const engineVersion = config.engineVersion ?? probeEngineVersion;

  let eventsErrorLogged = false;

  function resolveInside(root: string, requested: string): string | null {
    const resolved = path.resolve(root, requested);
    if (resolved !== root && !resolved.startsWith(root + path.sep)) return null;
    return resolved;
  }

  function sendJson(res: ServerResponse, status: number, body: unknown): void {
    const text = JSON.stringify(body);
    res.writeHead(status, { "content-type": "application/json; charset=utf-8", "content-length": Buffer.byteLength(text) });
    res.end(text);
  }

  async function readBody(req: IncomingMessage): Promise<unknown> {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    const text = Buffer.concat(chunks).toString("utf8");
    if (text.length === 0) return null;
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  async function handleTraces(res: ServerResponse): Promise<void> {
    let entries: { name: string; full: string }[] = [];
    try {
      const names = await readdir(traceDir);
      entries = names
        .filter((n) => n.startsWith(TRACE_PREFIX) && n.endsWith(".jsonl"))
        .sort()
        .map((n) => ({ name: n, full: path.join(traceDir, n) }));
    } catch {
      entries = []; // trace dir absent: an empty list is the honest state
    }
    const traces: TraceListing[] = [];
    for (const entry of entries) {
      try {
        const info = await stat(entry.full);
        const view = deriveTurns(entry.full);
        traces.push({ name: entry.name, path: entry.full, size: info.size, mtime: info.mtime.toISOString(), turns: view.turns.length });
      } catch {
        // a trace that vanishes mid-list is skipped, not fatal
      }
    }
    sendJson(res, 200, { traces });
  }

  async function handleTrace(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const requested = new URL(req.url ?? "/", "http://localhost").searchParams.get("path");
    if (requested === null) {
      sendJson(res, 400, { error: { cause: "missing-path" } });
      return;
    }
    const resolved = resolveInside(traceDir, requested);
    if (resolved === null) {
      sendJson(res, 400, { error: { cause: "path-outside-trace-dir" } });
      return;
    }
    try {
      await stat(resolved);
    } catch {
      sendJson(res, 404, { error: { cause: "trace-not-found" } });
      return;
    }
    sendJson(res, 200, { view: deriveTurns(resolved) });
  }

  async function handleFeed(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const params = new URL(req.url ?? "/", "http://localhost").searchParams;
    const requested = params.get("path");
    const rawCursor = params.get("cursor");
    if (requested === null) {
      sendJson(res, 400, { error: { cause: "missing-path" } });
      return;
    }
    const resolved = resolveInside(traceDir, requested);
    if (resolved === null) {
      sendJson(res, 400, { error: { cause: "path-outside-trace-dir" } });
      return;
    }
    const cursor = rawCursor === null || !/^\d+$/.test(rawCursor) ? 0 : Number(rawCursor);
    const state: TailState = createTailState(cursor);
    const delta = readTail(resolved, state);
    const view = deriveTurns(resolved); // re-derive whole-file; partial line is skipped, never a turn
    sendJson(res, 200, {
      path: resolved,
      cursor: delta.offset,
      pending: delta.pending,
      completeLines: delta.lines.length,
      turns: view.turns,
      windows: view.windows,
      skipped: view.skipped,
    });
  }

  async function handleVerify(req: IncomingMessage, res: ServerResponse, replay: boolean): Promise<void> {
    const body = (await readBody(req)) as { trace?: unknown; turn?: unknown; server?: unknown; manifest?: unknown } | null;
    const trace = typeof body?.trace === "string" ? body.trace : null;
    if (trace === null) {
      sendJson(res, 200, { ok: false, error: { cause: "missing-context" }, exitCode: null });
      return;
    }
    const resolved = resolveInside(traceDir, trace);
    if (resolved === null) {
      sendJson(res, 200, { ok: false, error: { cause: "path-outside-trace-dir" }, exitCode: null });
      return;
    }
    const turn = typeof body?.turn === "number" ? body.turn : undefined;
    if (replay && turn === undefined) {
      sendJson(res, 200, { ok: false, error: { cause: "missing-context" }, exitCode: null });
      return;
    }
    // Order matters: `--manifest-dir` must precede `--server`, which is
    // nargs=REMAINDER and would swallow everything after it.
    const extraArgs: string[] = [];
    if (typeof body?.manifest === "string") extraArgs.push("--manifest-dir", body.manifest);
    if (typeof body?.server === "string") extraArgs.push("--server", body.server);
    const result = await runVerifyJson({ trace: resolved, turn, extraArgs, env });
    sendJson(res, 200, result);
  }

  async function handleEvents(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const body = (await readBody(req)) as { trace?: unknown; turn?: unknown; kind?: unknown; t?: unknown } | null;
    const trace = typeof body?.trace === "string" ? body.trace : null;
    const kind = typeof body?.kind === "string" ? body.kind : null;
    const turn = typeof body?.turn === "number" ? body.turn : null;
    if (trace === null || kind === null) {
      sendJson(res, 200, { ok: false, error: { cause: "missing-context" }, exitCode: null });
      return;
    }
    const t = typeof body?.t === "string" ? body.t : now().toISOString();
    const record = JSON.stringify({ trace, turn, kind, t });
    try {
      await appendFile(eventsFile, record + "\n", { encoding: "utf8" });
      sendJson(res, 200, { ok: true });
    } catch (error) {
      if (!eventsErrorLogged) {
        log(`click log unwritable (${String(error)}); further failures stay silent`);
        eventsErrorLogged = true;
      }
      sendJson(res, 200, { ok: false, error: { cause: "events-unwritable" }, exitCode: null });
    }
  }

  async function serveStatic(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? "/", "http://localhost");
    const requested = url.pathname === "/" ? "index.html" : url.pathname.replace(/^\//, "");
    const resolved = resolveInside(distDir, requested);
    if (resolved === null) {
      res.writeHead(404).end("not found");
      return;
    }
    try {
      const content = await readFile(resolved);
      const ext = path.extname(resolved).toLowerCase();
      res.writeHead(200, { "content-type": MIME[ext] ?? "application/octet-stream" });
      res.end(content);
    } catch {
      if (requested === "index.html") {
        res.writeHead(503, { "content-type": "text/plain; charset=utf-8" });
        res.end(
          "The console SPA is not built here. Run `npm run build` in console/ and restart the server.\n",
        );
        return;
      }
      res.writeHead(404).end("not found");
    }
  }

  return httpCreateServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const method = req.method ?? "GET";
    const route = url.pathname;

    if (method === "GET" && route === "/health") {
      // The healthcheck contract, mirrored from the container's static server:
      // 200 {"ok": true, "engine": "<version>"} when the bundled engine reports
      // its version; 503 with an honest null when the probe fails — never a
      // claimed ok (the console's no-engine state renders honestly).
      void (async () => {
        const engine = await engineVersion();
        const ok = engine !== null;
        sendJson(res, ok ? 200 : 503, { ok, engine });
      })();
      return;
    }
    if (method === "GET" && route === "/api/traces") {
      void handleTraces(res);
      return;
    }
    if (method === "GET" && route === "/api/trace") {
      void handleTrace(req, res);
      return;
    }
    if (method === "GET" && route === "/api/feed") {
      void handleFeed(req, res);
      return;
    }
    if (method === "POST" && route === "/api/verify") {
      void handleVerify(req, res, false);
      return;
    }
    if (method === "POST" && route === "/api/replay") {
      void handleVerify(req, res, true);
      return;
    }
    if (method === "POST" && route === "/api/events") {
      void handleEvents(req, res);
      return;
    }
    if (route.startsWith("/api/")) {
      sendJson(res, 404, { error: { cause: "unknown-route" } });
      return;
    }
    void serveStatic(req, res);
  });
}