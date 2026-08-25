// The console container's server: node http only, serving the built SPA from
// console/dist plus a /health endpoint that reports the BUNDLED engine's
// version. Deliberately smaller than the dev server (console/src/server/):
// the container ships the SPA + health, and the engine is bundled so
// in-container verify/replay (the launch demo) work. The health endpoint
// probes the engine at runtime — if the engine cannot report its version the
// endpoint answers 503 with `ok: false`, never a claimed ok (the console's
// no-engine state renders honestly, per A2's tested path).

import { createServer } from "node:http";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const DIST_DIR = fileURLToPath(new URL("./dist", import.meta.url));
const PORT = Number(process.env.PORT ?? 8080);
const HOST = process.env.HOST ?? "0.0.0.0";

const MIME = {
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

function engineVersion() {
  try {
    const out = execFileSync(
      "python",
      ["-c", "import belay; print(belay.__version__)"],
      { timeout: 10_000, encoding: "utf8" },
    );
    const version = out.trim();
    return version.length > 0 ? version : null;
  } catch {
    return null;
  }
}

function resolveInside(root, requested) {
  const resolved = resolve(root, requested);
  if (resolved !== root && !resolved.startsWith(root + sep)) return null;
  return resolved;
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");

  if (req.method === "GET" && url.pathname === "/health") {
    const engine = engineVersion();
    const ok = engine !== null;
    const body = JSON.stringify({ ok, engine });
    res.writeHead(ok ? 200 : 503, {
      "content-type": "application/json; charset=utf-8",
      "content-length": Buffer.byteLength(body),
    });
    res.end(body);
    return;
  }

  const requested = url.pathname === "/" ? "index.html" : url.pathname.replace(/^\//, "");
  const resolved = resolveInside(DIST_DIR, requested);
  if (resolved === null) {
    res.writeHead(404).end("not found");
    return;
  }
  readFile(resolved)
    .then((content) => {
      const ext = extname(resolved).toLowerCase();
      res.writeHead(200, {
        "content-type": MIME[ext] ?? "application/octet-stream",
        "content-length": content.length,
      });
      res.end(content);
    })
    .catch(() => {
      if (requested === "index.html") {
        res.writeHead(503, { "content-type": "text/plain; charset=utf-8" });
        res.end("The console SPA is not built here. Run `npm run build` in console/ and restart the server.\n");
        return;
      }
      res.writeHead(404).end("not found");
    });
});

server.listen(PORT, HOST, () => {
  console.error(`belay console: http://${HOST}:${PORT} (SPA served from console/dist)`);
});