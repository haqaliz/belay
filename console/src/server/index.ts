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

import { statSync } from "node:fs";
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

/**
 * A command string split into argv tokens on whitespace. Deliberately NOT a shell
 * parser: no quoting, no escapes, no expansion — a token with a space in it is not
 * expressible here, and pretending otherwise would silently mis-split an operator's
 * command. An absent or blank value yields no tokens at all.
 */
export function splitCommand(command: string | undefined): string[] {
  if (typeof command !== "string") return [];
  const trimmed = command.trim();
  return trimmed.length === 0 ? [] : trimmed.split(/\s+/);
}

/**
 * The `<trace-stem>.manifests` sibling of a trace — the mint convention the gate writes
 * and `belay phase0 run` resolves — or `null` when it is not a directory that exists.
 *
 * `null` means NO `--manifest-dir` is passed, and `belay verify` requires the flag: the
 * engine's own "required: --manifest-dir" error is then the honest outcome. Guessing a
 * path that is not there would turn a missing replay context into a wall of UNVERIFIED
 * turns with a cause that blamed the snapshots rather than the setup.
 */
export function siblingManifestDir(tracePath: string): string | null {
  const candidate = path.join(
    path.dirname(tracePath),
    `${path.basename(tracePath, path.extname(tracePath))}.manifests`,
  );
  try {
    return statSync(candidate).isDirectory() ? candidate : null;
  } catch {
    return null;
  }
}

export function createServer(config: ServerConfig = {}): Server {
  const traceDir = config.traceDir ?? process.env.BELAY_CONSOLE_TRACE_DIR ?? path.join(homedir(), ".belay", "traces");
  const eventsFile =
    config.eventsFile ?? process.env.BELAY_CONSOLE_EVENTS ?? path.join(homedir(), ".belay", "console-events.jsonl");
  const distDir = config.distDir ?? fileURLToPath(new URL("../../dist", import.meta.url));
  const now = config.now ?? (() => new Date());
  const log = config.log ?? ((line: string) => console.error(`[belay-console] ${line}`));
  const env = config.env ?? process.env;
  const engineVersion = config.engineVersion ?? probeEngineVersion;

  // `BELAY_CONSOLE_VERIFY_TIMEOUT` (seconds) → `verify --timeout <seconds>`,
  // passed to the engine whenever the verify/replay handlers run. The engine's
  // default per-replay timeout (10s) cannot replay the demo capture's ~44s
  // `run_process` turns — those would render UNVERIFIED. Absent, or not a
  // positive integer, means nothing is passed (the engine default applies);
  // a value is never guessed.
  const rawVerifyTimeout = env.BELAY_CONSOLE_VERIFY_TIMEOUT;
  const verifyTimeoutSeconds =
    typeof rawVerifyTimeout === "string" && /^\d+$/.test(rawVerifyTimeout) && Number(rawVerifyTimeout) > 0
      ? Number(rawVerifyTimeout)
      : undefined;

  // `BELAY_CONSOLE_VERIFY_SERVER` — the default `--server` command for verify/replay,
  // whitespace-split into argv tokens. The engine's `--server` is nargs=REMAINDER: it
  // takes the command as separate tokens, so a single string would be exec'd as one
  // absurd filename ("python3 /srv/demo/server.py {workspace}"). The demo container
  // sets it so the console's verdicts are real re-execution rather than an operator
  // typing the command in by hand. Absent means nothing is passed and the engine's own
  // fail-closed error ("a server command is required") is the honest outcome.
  const defaultServerTokens = splitCommand(env.BELAY_CONSOLE_VERIFY_SERVER);

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
    //
    // A request-carried server/manifest always wins over the env defaults: the operator
    // typing a command into the replay dialog is a deliberate act, and the defaults exist
    // only so the packaged demo has a working replay context without one.
    const manifest =
      typeof body?.manifest === "string" && body.manifest.length > 0
        ? body.manifest
        : siblingManifestDir(resolved);
    const serverTokens =
      typeof body?.server === "string" && body.server.trim().length > 0
        ? splitCommand(body.server)
        : defaultServerTokens;
    const extraArgs: string[] = [];
    if (manifest !== null) extraArgs.push("--manifest-dir", manifest);
    if (serverTokens.length > 0) extraArgs.push("--server", ...serverTokens);
    // The wall around the subprocess is sized from the SAME per-replay budget the
    // engine was given: a whole-trace verify replays every turn, so a wall fixed at
    // one turn's worth would kill a run the operator authorised (and report it as an
    // engine failure). A trace we cannot derive counts as one turn — the wall only
    // shrinks, and a shrunken wall is a named error, never a verdict.
    let turnsInScope = 1;
    if (turn === undefined) {
      try {
        turnsInScope = deriveTurns(resolved).turns.length;
      } catch {
        turnsInScope = 1;
      }
    }
    const result = await runVerifyJson({
      trace: resolved,
      turn,
      extraArgs,
      env,
      replayTimeoutSeconds: verifyTimeoutSeconds,
      turnsInScope,
    });
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