// Endpoint tests for the console server, fully offline: synthetic fixture
// traces, the stub engine binary, and tmp dirs for events and the SPA dist.

import {
  appendFileSync,
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AddressInfo } from "node:net";
import { createServer, type ServerConfig } from "./index";

const fixtures = new URL("../../fixtures/", import.meta.url).pathname;
const stub = path.join(fixtures, "stub-engine.mjs");
const cleanFixture = path.join(fixtures, "trace-clean.jsonl");

chmodSync(stub, 0o755);

interface ServerHarness {
  base: string;
  traceDir: string;
  eventsFile: string;
  stop: () => Promise<void>;
}

async function startServer(config: ServerConfig = {}): Promise<ServerHarness> {
  const traceDir = mkdtempSync(path.join(tmpdir(), "belay-api-trace-"));
  copyFileSync(cleanFixture, path.join(traceDir, "trace-clean.jsonl"));
  copyFileSync(path.join(fixtures, "trace-failed.jsonl"), path.join(traceDir, "trace-failed.jsonl"));
  copyFileSync(path.join(fixtures, "trace-unverified.jsonl"), path.join(traceDir, "trace-unverified.jsonl"));
  const eventsFile = path.join(mkdtempSync(path.join(tmpdir(), "belay-api-events-")), "console-events.jsonl");
  const distDir = mkdtempSync(path.join(tmpdir(), "belay-api-dist-"));
  writeFileSync(path.join(distDir, "index.html"), "<!doctype html><title>console</title>");
  writeFileSync(path.join(distDir, "asset.js"), "console.log('asset')");

  const server = createServer({
    traceDir,
    eventsFile,
    distDir,
    env: { ...process.env, BELAY_CONSOLE_ENGINE: stub },
    ...config,
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address() as AddressInfo;
  const base = `http://127.0.0.1:${address.port}`;
  const stop = () =>
    new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())));
  return { base, traceDir, eventsFile, stop };
}

let harness: ServerHarness;

beforeEach(async () => {
  harness = await startServer();
});

afterEach(async () => {
  await harness.stop();
  rmSync(harness.traceDir, { recursive: true, force: true });
  rmSync(path.dirname(harness.eventsFile), { recursive: true, force: true });
});

describe("GET /api/traces", () => {
  it("lists the fixture traces with their derived turn counts", async () => {
    const res = await fetch(`${harness.base}/api/traces`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { traces: { name: string; turns: number }[] };
    expect(body.traces.map((t) => [t.name, t.turns])).toEqual([
      ["trace-clean.jsonl", 2],
      ["trace-failed.jsonl", 1],
      ["trace-unverified.jsonl", 1],
    ]);
  });

  it("lists nothing (honestly) when the trace dir is absent", async () => {
    const local = await startServer({ traceDir: path.join(tmpdir(), "belay-no-such-dir-xyz") });
    try {
      const res = await fetch(`${local.base}/api/traces`);
      const body = (await res.json()) as { traces: unknown[] };
      expect(body.traces).toEqual([]);
    } finally {
      await local.stop();
    }
  });
});

describe("GET /api/trace", () => {
  it("derives one trace into turns", async () => {
    const res = await fetch(`${harness.base}/api/trace?path=${encodeURIComponent("trace-clean.jsonl")}`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { view: { turns: { tool: string; ordinal: number }[] } };
    expect(body.view.turns.map((t) => t.tool)).toEqual(["write_note", "list_files"]);
    expect(body.view.turns[1].ordinal).toBe(1);
  });

  it("404s a missing trace", async () => {
    const res = await fetch(`${harness.base}/api/trace?path=${encodeURIComponent("trace-nope.jsonl")}`);
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error: { cause: string } };
    expect(body.error.cause).toBe("trace-not-found");
  });

  it("rejects a path that escapes the trace dir", async () => {
    const res = await fetch(`${harness.base}/api/trace?path=${encodeURIComponent("../../package.json")}`);
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: { cause: string } };
    expect(body.error.cause).toBe("path-outside-trace-dir");
  });
});

describe("GET /api/feed", () => {
  it("returns turns, a cursor, and no pending line for a complete trace", async () => {
    const res = await fetch(`${harness.base}/api/feed?path=${encodeURIComponent("trace-clean.jsonl")}&cursor=0`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { cursor: number; pending: string | null; turns: unknown[]; completeLines: number };
    expect(body.turns).toHaveLength(2);
    expect(body.pending).toBeNull();
    expect(body.completeLines).toBe(9);
    expect(body.cursor).toBeGreaterThan(0);
  });

  it("holds a partial final line as PENDING — never a turn, cursor stays put", async () => {
    const live = path.join(harness.traceDir, "trace-live.jsonl");
    copyFileSync(cleanFixture, live);
    const first = await fetch(`${harness.base}/api/feed?path=${encodeURIComponent("trace-live.jsonl")}&cursor=0`);
    const firstBody = (await first.json()) as { cursor: number; pending: string | null; turns: unknown[] };
    expect(firstBody.turns).toHaveLength(2);
    expect(firstBody.pending).toBeNull();

    appendFileSync(live, '{"v":1,"kind":"frame","seq":99,"dir":"c2s","raw":"' + Buffer.from(JSON.stringify({ jsonrpc: "2.0", id: 9, method: "tools/call", params: { name: "ping", arguments: {} } })).toString("base64") + '"');
    const second = await fetch(
      `${harness.base}/api/feed?path=${encodeURIComponent("trace-live.jsonl")}&cursor=${firstBody.cursor}`,
    );
    const secondBody = (await second.json()) as { pending: string | null; turns: unknown[] };
    expect(secondBody.turns).toHaveLength(2); // the partial line is NOT a turn
    expect(secondBody.pending).toContain('"seq":99');
  });

  it("appends a turn once the partial line completes", async () => {
    const live = path.join(harness.traceDir, "trace-live2.jsonl");
    copyFileSync(cleanFixture, live);
    const first = await fetch(`${harness.base}/api/feed?path=${encodeURIComponent("trace-live2.jsonl")}&cursor=0`);
    const firstBody = (await first.json()) as { cursor: number };

    const partial = '{"v":1,"kind":"frame","seq":99,"dir":"c2s","raw":"' + Buffer.from(JSON.stringify({ jsonrpc: "2.0", id: 9, method: "tools/call", params: { name: "ping", arguments: {} } })).toString("base64") + '"';
    appendFileSync(live, partial);
    const mid = await fetch(`${harness.base}/api/feed?path=${encodeURIComponent("trace-live2.jsonl")}&cursor=${firstBody.cursor}`);
    const midBody = (await mid.json()) as { pending: string | null; turns: unknown[] };
    expect(midBody.turns).toHaveLength(2);
    expect(midBody.pending).not.toBeNull();

    appendFileSync(live, '}\n');
    const done = await fetch(`${harness.base}/api/feed?path=${encodeURIComponent("trace-live2.jsonl")}&cursor=${firstBody.cursor}`);
    const doneBody = (await done.json()) as { pending: string | null; turns: unknown[] };
    expect(doneBody.pending).toBeNull();
    expect(doneBody.turns).toHaveLength(3);
  });
});

describe("POST /api/verify and /api/replay", () => {
  it("verifies a whole trace through the engine (stub) and returns the doc", async () => {
    const res = await fetch(`${harness.base}/api/verify`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ trace: "trace-clean.jsonl" }),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; doc: { turns: unknown[]; coverage: unknown } };
    expect(body.ok).toBe(true);
    expect(body.doc.turns).toHaveLength(2);
    expect(body.doc.coverage).toBeTruthy();
  });

  it("replays one turn (verify --turn N) with the recorded context", async () => {
    const res = await fetch(`${harness.base}/api/replay`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ trace: "trace-clean.jsonl", turn: 1, server: "python server.py", manifest: "/tmp/manifest" }),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; doc: { turns: { ordinal: number; tool: string }[]; trajectory: unknown } };
    expect(body.ok).toBe(true);
    expect(body.doc.turns).toHaveLength(1);
    expect(body.doc.turns[0]).toMatchObject({ ordinal: 1, tool: "list_files" });
    expect(body.doc.trajectory).toBeNull();
  });

  it("renders a FAIL document's verdicts despite the non-zero engine exit", async () => {
    const res = await fetch(`${harness.base}/api/verify`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ trace: "trace-failed.jsonl" }),
    });
    const body = (await res.json()) as { ok: boolean; doc: { turns: { status: string }[] } };
    expect(body.ok).toBe(true);
    expect(body.doc.turns[0].status).toBe("FAIL");
  });

  it("returns a named engine-not-found error without crashing", async () => {
    const local = await startServer({ env: { ...process.env, BELAY_CONSOLE_ENGINE: "/nonexistent/belay" } });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl" }),
      });
      expect(res.status).toBe(200);
      const body = (await res.json()) as { ok: boolean; error: { cause: string } };
      expect(body.ok).toBe(false);
      expect(body.error.cause).toBe("engine-not-found");
    } finally {
      await local.stop();
    }
  });

  it("missing context is a named error, never a verdict", async () => {
    const res = await fetch(`${harness.base}/api/replay`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ trace: "trace-clean.jsonl" }), // no turn
    });
    const body = (await res.json()) as { ok: boolean; error: { cause: string } };
    expect(body.ok).toBe(false);
    expect(body.error.cause).toBe("missing-context");
  });

  it("passes --timeout from BELAY_CONSOLE_VERIFY_TIMEOUT (the demo's slow turns)", async () => {
    const local = await startServer({
      env: {
        ...process.env,
        BELAY_CONSOLE_ENGINE: stub,
        BELAY_CONSOLE_VERIFY_TIMEOUT: "300",
        STUB_ENGINE_MODE: "argv",
      },
    });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl" }),
      });
      const body = (await res.json()) as { ok: boolean; doc: { argv: string[] } };
      expect(body.ok).toBe(true);
      expect(body.doc.argv).toContain("--timeout");
      expect(body.doc.argv).toContain("300");
      const traceIndex = body.doc.argv.findIndex((a) => a.endsWith("trace-clean.jsonl"));
      expect(traceIndex).toBeGreaterThan(body.doc.argv.indexOf("--timeout"));
    } finally {
      await local.stop();
    }
  });

  it("passes nothing when BELAY_CONSOLE_VERIFY_TIMEOUT is absent", async () => {
    const local = await startServer({
      env: { ...process.env, BELAY_CONSOLE_ENGINE: stub, STUB_ENGINE_MODE: "argv" },
    });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl" }),
      });
      const body = (await res.json()) as { ok: boolean; doc: { argv: string[] } };
      expect(body.ok).toBe(true);
      expect(body.doc.argv).not.toContain("--timeout");
    } finally {
      await local.stop();
    }
  });

  it("treats a non-numeric BELAY_CONSOLE_VERIFY_TIMEOUT as absent (never a guessed value)", async () => {
    const local = await startServer({
      env: {
        ...process.env,
        BELAY_CONSOLE_ENGINE: stub,
        BELAY_CONSOLE_VERIFY_TIMEOUT: "soon",
        STUB_ENGINE_MODE: "argv",
      },
    });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl" }),
      });
      const body = (await res.json()) as { ok: boolean; doc: { argv: string[] } };
      expect(body.ok).toBe(true);
      expect(body.doc.argv).not.toContain("--timeout");
    } finally {
      await local.stop();
    }
  });
});

describe("verify replay-context defaults (the demo capture's verdicts)", () => {
  it("injects BELAY_CONSOLE_VERIFY_SERVER as whitespace-split --server tokens after the trace", async () => {
    mkdirSync(path.join(harness.traceDir, "trace-clean.manifests"), { recursive: true });
    const local = await startServer({
      traceDir: harness.traceDir,
      env: {
        ...process.env,
        BELAY_CONSOLE_ENGINE: stub,
        STUB_ENGINE_MODE: "argv",
        BELAY_CONSOLE_VERIFY_SERVER: "python3 /srv/demo/server.py {workspace}",
      },
    });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl" }),
      });
      const body = (await res.json()) as { ok: boolean; doc: { argv: string[] } };
      expect(body.ok).toBe(true);
      const argv = body.doc.argv;
      expect(argv).toContain("--server");
      const serverIndex = argv.indexOf("--server");
      expect(argv.slice(serverIndex + 1)).toEqual([
        "python3",
        "/srv/demo/server.py",
        "{workspace}",
      ]);
      expect(serverIndex).toBeGreaterThan(argv.findIndex((a) => a.endsWith("trace-clean.jsonl")));
    } finally {
      await local.stop();
    }
  });

  it("defaults --manifest-dir to the trace's sibling <stem>.manifests when it exists", async () => {
    mkdirSync(path.join(harness.traceDir, "trace-clean.manifests"), { recursive: true });
    const local = await startServer({
      traceDir: harness.traceDir,
      env: { ...process.env, BELAY_CONSOLE_ENGINE: stub, STUB_ENGINE_MODE: "argv" },
    });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl" }),
      });
      const body = (await res.json()) as { ok: boolean; doc: { argv: string[] } };
      expect(body.ok).toBe(true);
      const argv = body.doc.argv;
      const manifestIndex = argv.indexOf("--manifest-dir");
      expect(manifestIndex).toBeGreaterThan(-1);
      expect(argv[manifestIndex + 1]).toBe(path.join(harness.traceDir, "trace-clean.manifests"));
      // The pinned argv order (engine.test.ts): the trace positional first, then
      // --manifest-dir, then --server LAST — `verify --server` is nargs=REMAINDER and
      // swallows everything after it.
      expect(manifestIndex).toBeGreaterThan(argv.findIndex((a) => a.endsWith("trace-clean.jsonl")));
    } finally {
      await local.stop();
    }
  });

  it("passes no --manifest-dir when the sibling does not exist (the engine's fail-closed error is the honest outcome)", async () => {
    const local = await startServer({
      traceDir: harness.traceDir,
      env: { ...process.env, BELAY_CONSOLE_ENGINE: stub, STUB_ENGINE_MODE: "argv" },
    });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl" }),
      });
      const body = (await res.json()) as { ok: boolean; doc: { argv: string[] } };
      expect(body.ok).toBe(true);
      expect(body.doc.argv).not.toContain("--manifest-dir");
    } finally {
      await local.stop();
    }
  });

  it("lets a request-carried server/manifest win over the env defaults", async () => {
    mkdirSync(path.join(harness.traceDir, "trace-clean.manifests"), { recursive: true });
    const local = await startServer({
      traceDir: harness.traceDir,
      env: {
        ...process.env,
        BELAY_CONSOLE_ENGINE: stub,
        STUB_ENGINE_MODE: "argv",
        BELAY_CONSOLE_VERIFY_SERVER: "python3 /srv/demo/server.py {workspace}",
      },
    });
    try {
      const res = await fetch(`${local.base}/api/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          trace: "trace-clean.jsonl",
          server: "python my-own-server.py",
          manifest: "/tmp/my-manifests",
        }),
      });
      const body = (await res.json()) as { ok: boolean; doc: { argv: string[] } };
      expect(body.ok).toBe(true);
      const argv = body.doc.argv;
      expect(argv.slice(argv.indexOf("--server") + 1)).toEqual(["python", "my-own-server.py"]);
      expect(argv[argv.indexOf("--manifest-dir") + 1]).toBe("/tmp/my-manifests");
      expect(argv).not.toContain("/srv/demo/server.py");
    } finally {
      await local.stop();
    }
  });
});

describe("POST /api/events", () => {
  it("appends exactly one JSONL record per click, stamped by the server clock", async () => {
    const clicks = [
      { trace: "trace-clean.jsonl", turn: 0, kind: "expand-diff" },
      { trace: "trace-clean.jsonl", turn: null, kind: "open-trace" },
    ];
    for (const click of clicks) {
      const res = await fetch(`${harness.base}/api/events`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(click),
      });
      const body = (await res.json()) as { ok: boolean };
      expect(body.ok).toBe(true);
    }
    const lines = readFileSync(harness.eventsFile, "utf8").trim().split("\n");
    expect(lines).toHaveLength(2);
    const records = lines.map((l) => JSON.parse(l));
    expect(records[0]).toMatchObject({ trace: "trace-clean.jsonl", turn: 0, kind: "expand-diff" });
    expect(records[1]).toMatchObject({ trace: "trace-clean.jsonl", turn: null, kind: "open-trace" });
    expect(new Date(records[0].t).toISOString()).toBe(records[0].t);
  });

  it("honours an injected clock", async () => {
    const fixed = new Date("2026-08-24T10:00:00.000Z");
    const local = await startServer({ now: () => fixed });
    try {
      await fetch(`${local.base}/api/events`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl", turn: 1, kind: "expand-args" }),
      });
      const lines = readFileSync(local.eventsFile, "utf8").trim().split("\n");
      expect(JSON.parse(lines[0]).t).toBe("2026-08-24T10:00:00.000Z");
    } finally {
      await local.stop();
    }
  });

  it("degrades silently (ok:false) when the events file is unwritable, and logs once", async () => {
    const local = await startServer({ eventsFile: "/nonexistent-dir/console-events.jsonl" });
    try {
      for (let i = 0; i < 3; i += 1) {
        const res = await fetch(`${local.base}/api/events`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ trace: "trace-clean.jsonl", turn: i, kind: "expand" }),
        });
        const body = (await res.json()) as { ok: boolean; error: { cause: string } };
        expect(body.ok).toBe(false);
        expect(body.error.cause).toBe("events-unwritable");
      }
    } finally {
      await local.stop();
    }
  });
});

describe("static SPA serving", () => {
  it("serves index.html from the dist dir", async () => {
    const res = await fetch(`${harness.base}/`);
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("<title>console</title>");
  });

  it("serves assets with their content types", async () => {
    const res = await fetch(`${harness.base}/asset.js`);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/javascript");
    expect(await res.text()).toBe("console.log('asset')");
  });

  it("returns a named 503 when the SPA is not built", async () => {
    const local = await startServer({ distDir: path.join(tmpdir(), "belay-no-dist-xyz") });
    try {
      const res = await fetch(`${local.base}/`);
      expect(res.status).toBe(503);
      expect(await res.text()).toContain("npm run build");
    } finally {
      await local.stop();
    }
  });
});

describe("GET /health", () => {
  it("reports ok with the engine version when the probe succeeds", async () => {
    const local = await startServer({ engineVersion: async () => "0.23.0" });
    try {
      const res = await fetch(`${local.base}/health`);
      expect(res.status).toBe(200);
      const body = (await res.json()) as { ok: boolean; engine: string | null };
      expect(body).toEqual({ ok: true, engine: "0.23.0" });
    } finally {
      await local.stop();
    }
  });

  it("answers 503 with an honest null when the engine probe fails", async () => {
    const local = await startServer({ engineVersion: async () => null });
    try {
      const res = await fetch(`${local.base}/health`);
      expect(res.status).toBe(503);
      const body = (await res.json()) as { ok: boolean; engine: string | null };
      expect(body).toEqual({ ok: false, engine: null });
    } finally {
      await local.stop();
    }
  });
});

const approvalClock = () => new Date("2026-10-21T10:00:00.000Z");
const approvalCreated = approvalClock().getTime() / 1000 - 5;

function approvalRequest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    hold_id: "hold-1",
    tool: "write_note",
    request_id: 2,
    triggers: ["destructive"],
    created_at: approvalCreated,
    timeout: 60,
    ...overrides,
  };
}

function approvalDir(): string {
  return mkdtempSync(path.join(tmpdir(), "belay-api-approvals-"));
}

function writeRequest(dir: string, body: Record<string, unknown>, name?: string): void {
  mkdirSync(path.join(dir, "requests"), { recursive: true });
  writeFileSync(path.join(dir, "requests", `${name ?? String(body.hold_id)}.json`), JSON.stringify(body));
}

function writeDecision(dir: string, holdId: string, body: unknown): void {
  mkdirSync(path.join(dir, "decisions"), { recursive: true });
  writeFileSync(path.join(dir, "decisions", `${holdId}.json`), JSON.stringify(body));
}

async function withApprovals(
  run: (local: ServerHarness, dir: string) => Promise<void>,
  dir = approvalDir(),
): Promise<void> {
  const local = await startServer({ approvalDir: dir, now: approvalClock });
  try {
    await run(local, dir);
  } finally {
    await local.stop();
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("GET /api/approvals", () => {
  interface ListBody {
    configured: boolean;
    holds: {
      hold_id: string;
      tool: string;
      triggers: string[];
      request_id: unknown;
      created_at: number;
      timeout: number;
      expires_at: number;
    }[];
  }

  it("lists a pending hold with its tool, triggers and expiry", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, request());
      const res = await fetch(`${local.base}/api/approvals`);
      expect(res.status).toBe(200);
      const body = (await res.json()) as ListBody;
      expect(body.configured).toBe(true);
      expect(body.holds).toHaveLength(1);
      expect(body.holds[0]).toMatchObject({
        hold_id: "hold-1",
        tool: "write_note",
        triggers: ["destructive"],
        request_id: 2,
      });
    });
  });

  it("computes expires_at as created_at + timeout", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, request());
      const res = await fetch(`${local.base}/api/approvals`);
      const body = (await res.json()) as ListBody;
      expect(body.holds[0].expires_at).toBe(created + 60);
    });
  });

  it("omits a hold that already has a decision", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, request());
      writeDecision(dir, "hold-1", { decision: "approve" });
      const res = await fetch(`${local.base}/api/approvals`);
      const body = (await res.json()) as ListBody;
      expect(body.holds).toEqual([]);
    });
  });

  it("omits a hold past created_at + timeout", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, request({ created_at: created - 120, timeout: 60 }));
      const res = await fetch(`${local.base}/api/approvals`);
      const body = (await res.json()) as ListBody;
      expect(body.holds).toEqual([]);
    });
  });

  it("skips a malformed request file without breaking the list", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, request());
      mkdirSync(path.join(dir, "requests"), { recursive: true });
      writeFileSync(path.join(dir, "requests", "broken.json"), "{not json");
      writeFileSync(path.join(dir, "requests", "missing-fields.json"), JSON.stringify({ hold_id: "missing-fields" }));
      const res = await fetch(`${local.base}/api/approvals`);
      expect(res.status).toBe(200);
      const body = (await res.json()) as ListBody;
      expect(body.holds.map((h) => h.hold_id)).toEqual(["hold-1"]);
    });
  });

  it("reports configured:false and an empty list when the approval dir is not set", async () => {
    const env = { ...process.env };
    delete env.BELAY_APPROVAL_DIR;
    const local = await startServer({ env });
    try {
      const res = await fetch(`${local.base}/api/approvals`);
      expect(res.status).toBe(200);
      const body = (await res.json()) as ListBody;
      expect(body).toEqual({ configured: false, holds: [] });
    } finally {
      await local.stop();
    }
  });

  it("reads BELAY_APPROVAL_DIR from the environment", async () => {
    const dir = approvalDir();
    writeRequest(dir, request());
    const local = await startServer({ env: { ...process.env, BELAY_APPROVAL_DIR: dir }, now: clock });
    try {
      const res = await fetch(`${local.base}/api/approvals`);
      const body = (await res.json()) as ListBody;
      expect(body.configured).toBe(true);
      expect(body.holds).toHaveLength(1);
    } finally {
      await local.stop();
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("does not break when the configured approval dir is missing", async () => {
    await withApprovals(async (local, dir) => {
      rmSync(dir, { recursive: true, force: true });
      const res = await fetch(`${local.base}/api/approvals`);
      expect(res.status).toBe(200);
      const body = (await res.json()) as ListBody;
      expect(body).toEqual({ configured: true, holds: [] });
    });
  });
});

describe("POST /api/approvals/decision", () => {
  interface ErrorBody {
    error: { cause: string };
  }

  function decide(base: string, body: unknown): Promise<Response> {
    return fetch(`${base}/api/approvals/decision`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function decisionBytes(dir: string, holdId: string): string {
    return readFileSync(path.join(dir, "decisions", `${holdId}.json`), "utf8");
  }

  it("approves with exactly the engine's decision file, atomically", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, approvalRequest());
      const res = await decide(local.base, { hold_id: "hold-1", decision: "approve" });
      expect(res.status).toBe(200);
      expect(decisionBytes(dir, "hold-1")).toBe('{"decision":"approve"}');
      // temp+rename leaves no partial and no temp file behind
      expect(readdirSync(path.join(dir, "decisions"))).toEqual(["hold-1.json"]);
    });
  });

  it("denies with the reason, exact bytes", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, approvalRequest());
      const res = await decide(local.base, { hold_id: "hold-1", decision: "deny", reason: "not this tree" });
      expect(res.status).toBe(200);
      expect(decisionBytes(dir, "hold-1")).toBe('{"decision":"deny","reason":"not this tree"}');
    });
  });

  it("removes the hold from the list once decided", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, approvalRequest());
      await decide(local.base, { hold_id: "hold-1", decision: "approve" });
      const res = await fetch(`${local.base}/api/approvals`);
      const body = (await res.json()) as { holds: unknown[] };
      expect(body.holds).toEqual([]);
    });
  });

  it("refuses a second decision with already-decided", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, approvalRequest());
      await decide(local.base, { hold_id: "hold-1", decision: "approve" });
      const res = await decide(local.base, { hold_id: "hold-1", decision: "deny", reason: "changed my mind" });
      expect(res.status).toBe(409);
      expect(((await res.json()) as ErrorBody).error.cause).toBe("already-decided");
      expect(decisionBytes(dir, "hold-1")).toBe('{"decision":"approve"}');
    });
  });

  it("refuses an expired hold with hold-expired and writes nothing", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, approvalRequest({ created_at: approvalCreated - 120, timeout: 60 }));
      const res = await decide(local.base, { hold_id: "hold-1", decision: "approve" });
      expect(res.status).toBe(409);
      expect(((await res.json()) as ErrorBody).error.cause).toBe("hold-expired");
      expect(existsSync(path.join(dir, "decisions", "hold-1.json"))).toBe(false);
    });
  });

  it("refuses an unknown hold with hold-not-found", async () => {
    await withApprovals(async (local) => {
      const res = await decide(local.base, { hold_id: "hold-nope", decision: "approve" });
      expect(res.status).toBe(409);
      expect(((await res.json()) as ErrorBody).error.cause).toBe("hold-not-found");
    });
  });

  it.each(["../x", "../../etc/passwd", "a/b", "", "a\\b", "hold id"])(
    "rejects the hold id %j with bad-hold-id",
    async (holdId) => {
      await withApprovals(async (local) => {
        const res = await decide(local.base, { hold_id: holdId, decision: "approve" });
        expect(res.status).toBe(400);
        expect(((await res.json()) as ErrorBody).error.cause).toBe("bad-hold-id");
      });
    },
  );

  it("rejects an unknown decision with bad-decision", async () => {
    await withApprovals(async (local, dir) => {
      writeRequest(dir, approvalRequest());
      const res = await decide(local.base, { hold_id: "hold-1", decision: "maybe" });
      expect(res.status).toBe(400);
      expect(((await res.json()) as ErrorBody).error.cause).toBe("bad-decision");
      expect(existsSync(path.join(dir, "decisions", "hold-1.json"))).toBe(false);
    });
  });

  it("refuses with approval-not-configured when no approval dir is set", async () => {
    const env = { ...process.env };
    delete env.BELAY_APPROVAL_DIR;
    const local = await startServer({ env });
    try {
      const res = await decide(local.base, { hold_id: "hold-1", decision: "approve" });
      expect(res.status).toBe(409);
      expect(((await res.json()) as ErrorBody).error.cause).toBe("approval-not-configured");
    } finally {
      await local.stop();
    }
  });
});

describe("routing", () => {
  it("404s unknown API routes with a named error", async () => {
    const res = await fetch(`${harness.base}/api/nope`);
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error: { cause: string } };
    expect(body.error.cause).toBe("unknown-route");
  });
});