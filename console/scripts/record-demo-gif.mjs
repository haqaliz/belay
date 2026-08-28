#!/usr/bin/env node
// Records `assets/belay-demo.gif`: the console rendering the COMMITTED demo capture.
//
// MANUAL BY DESIGN — never CI. It needs a real browser (Playwright's chromium,
// downloaded once per machine) and it re-executes the capture through the engine,
// which takes minutes. The gif is committed; nothing regenerates it on a push.
//
//   npm run record:demo
//
// What makes the output deterministic is NOT the clock: it is that the subject is a
// frozen artifact and the beats are driven by STATE (wait for the verdict to land),
// while the gif's frame sequence and per-frame delays are fixed constants below. A
// fixed sleep would be a lie here — the capture's `run_process` turns re-run a real
// suite, so the verdict takes as long as it takes.
//
// The PNG decode and the GIF encode both happen INSIDE the browser page: it already
// has a PNG decoder (canvas) and gifenc is pure JS, so screenshots go in as small
// base64 PNGs and one small base64 GIF comes back. No ffmpeg, no image dependency in
// node.

import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CONSOLE_DIR = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const REPO_ROOT = path.resolve(CONSOLE_DIR, "..");

// --- the recording's constants -------------------------------------------------------
//
// The viewport matches the README's `<img width="820">` so the gif is rendered at its
// natural size rather than resampled by the browser.
const VIEWPORT = { width: 820, height: 560 };
const OUTPUT = path.join(REPO_ROOT, "assets", "belay-demo.gif");
//: Per-frame hold, in ms. The last beat holds longest — the reader needs time on the
//: verdict, which is the whole point of the image.
const BEAT_MS = 1400;
const FINAL_BEAT_MS = 3600;
//: The frame budget. gifenc holds every frame in memory and the README wants a small
//: asset; the script refuses to encode more than this rather than emit a huge gif.
const MAX_FRAMES = 30;

const env = process.env;
const traceDir = path.resolve(REPO_ROOT, env.BELAY_DEMO_TRACE_DIR ?? "demo/capture");
const verifyServer =
  env.BELAY_CONSOLE_VERIFY_SERVER ?? `python3 ${path.join(REPO_ROOT, "demo", "server.py")} {workspace}`;
const verifyTimeout = env.BELAY_CONSOLE_VERIFY_TIMEOUT ?? "300";
const engine = env.BELAY_CONSOLE_ENGINE ?? defaultEngine();
const port = Number(env.BELAY_CONSOLE_PORT ?? 8799);
//: How long to wait for the verdict to land. The capture's suite turns take ~44s each,
//: so a whole-trace verify is minutes; this is a giving-up bound, not a pacing knob.
const VERDICT_TIMEOUT_MS = Number(env.BELAY_DEMO_VERDICT_TIMEOUT_MS ?? 900_000);
//: Optional: also write each beat as a PNG here, for inspecting the composition.
const frameDir = env.BELAY_DEMO_FRAME_DIR ? path.resolve(env.BELAY_DEMO_FRAME_DIR) : null;
//: Optional: re-encode an EXISTING frame dir instead of driving the console. Tuning the
//: palette or the beat timings should not cost another few minutes of real re-execution.
const fromFrames = env.BELAY_DEMO_FROM_FRAMES ? path.resolve(env.BELAY_DEMO_FROM_FRAMES) : null;
//: GIF palette size (max 256). The console is flat UI, so a smaller palette is close to
//: lossless and meaningfully smaller on disk.
const PALETTE_SIZE = Number(env.BELAY_DEMO_PALETTE ?? 64);

function defaultEngine() {
  const venv = path.join(REPO_ROOT, ".venv", "bin", "belay");
  try {
    readFileSync(venv);
    return venv;
  } catch {
    return "belay"; // PATH, same as the server's own default
  }
}

function fail(message) {
  console.error(`record-demo-gif: ${message}`);
  process.exit(1);
}

async function main() {
  let chromium;
  try {
    ({ chromium } = await import("playwright"));
  } catch {
    fail("playwright is not installed. Run `npm install` in console/, then `npx playwright install chromium`.");
  }

  const server = fromFrames === null ? await startConsoleServer() : null;
  let browser;
  try {
    try {
      browser = await chromium.launch();
    } catch (e) {
      fail(
        "could not launch chromium. Playwright's browser is a separate, per-machine " +
          `download: run \`npx playwright install chromium\` in console/.\n  (${e.message})`,
      );
    }
    const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 1 });
    const frames = fromFrames === null ? await record(page, `http://127.0.0.1:${port}`) : replayFrames();
    const gif = await encode(page, frames);
    await browser.close();
    browser = undefined;

    mkdirSync(path.dirname(OUTPUT), { recursive: true });
    writeFileSync(OUTPUT, gif);
    const kb = (gif.length / 1024).toFixed(1);
    console.log(`record-demo-gif: wrote ${OUTPUT} — ${frames.length} frames, ${kb}K`);
    if (gif.length > 1024 * 1024) {
      console.error("record-demo-gif: WARNING — over 1MB; the README wants a small asset.");
    }
  } finally {
    if (browser !== undefined) await browser.close().catch(() => {});
    if (server !== null) server.kill("SIGTERM");
  }
}

/** Load a previously recorded frame dir, in beat order, with the same delays. */
function replayFrames() {
  const names = readdirSync(fromFrames).filter((n) => n.endsWith(".png")).sort();
  if (names.length === 0) fail(`no frame PNGs under ${fromFrames}.`);
  return names.map((name, i) => ({
    png: readFileSync(path.join(fromFrames, name)).toString("base64"),
    delay: i === names.length - 1 ? FINAL_BEAT_MS : BEAT_MS,
  }));
}

/** Spawn the console's own server (the one the container runs) and wait for it to answer. */
async function startConsoleServer() {
  const child = spawn("npx", ["tsx", "src/server/run.ts"], {
    cwd: CONSOLE_DIR,
    env: {
      ...env,
      BELAY_CONSOLE_TRACE_DIR: traceDir,
      BELAY_CONSOLE_ENGINE: engine,
      BELAY_CONSOLE_VERIFY_SERVER: verifyServer,
      BELAY_CONSOLE_VERIFY_TIMEOUT: verifyTimeout,
      BELAY_CONSOLE_PORT: String(port),
      BELAY_CONSOLE_HOST: "127.0.0.1",
    },
    stdio: ["ignore", "inherit", "inherit"],
  });

  const deadline = Date.now() + 30_000;
  for (;;) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/traces`);
      const body = await res.json();
      if (Array.isArray(body.traces) && body.traces.length > 0) return child;
      if (Date.now() > deadline) {
        child.kill("SIGTERM");
        fail(`no traces under ${traceDir} — nothing to record.`);
      }
    } catch {
      if (Date.now() > deadline) {
        child.kill("SIGTERM");
        fail(`the console server did not answer on :${port} within 30s.`);
      }
    }
    await new Promise((r) => setTimeout(r, 250));
  }
}

/**
 * The scripted beats, each a screenshot. Every step waits on a SELECTOR — the state
 * the beat is about — so the sequence is the same on every machine even though the
 * timings are not.
 */
async function record(page, base) {
  const frames = [];
  const shoot = async (delay) => {
    const png = await page.screenshot({ type: "png" });
    // The operator's inspection seam: with BELAY_DEMO_FRAME_DIR set, every beat is
    // also written out as a PNG so a bad composition is diagnosable frame by frame
    // rather than by squinting at the gif.
    if (frameDir !== null) {
      mkdirSync(frameDir, { recursive: true });
      writeFileSync(path.join(frameDir, `frame-${String(frames.length).padStart(2, "0")}.png`), png);
    }
    frames.push({ png: png.toString("base64"), delay });
  };

  await page.goto(base, { waitUntil: "networkidle" });

  // 1 — the feed: the console found the capture and is streaming its turns. Waiting
  //     for a ROW, not just the trace pill: the pill exists as soon as /api/traces
  //     answers, while the turns arrive on the next feed poll — shooting on the pill
  //     alone gives an empty "0 turns" frame on a fast machine and a full one on a
  //     slow one, which is exactly the nondeterminism this script exists to avoid.
  await page.waitForSelector(".trace-pill");
  await page.waitForSelector(".feed-row");
  await shoot(BEAT_MS);

  // 2 — into the trace view. The engine is re-executing and the console says so,
  //     showing NO verdicts while it does — never a placeholder PASS. (A trace whose
  //     verify returns instantly would skip this beat; the demo capture re-runs a real
  //     suite, so it cannot.)
  await page.click(".feed-row");
  await page.waitForSelector(".trace-view");
  try {
    await page.waitForSelector(".engine-pending", { timeout: 60_000 });
  } catch {
    fail("the 'verifying…' beat never appeared — this trace verifies too fast to record.");
  }
  await shoot(BEAT_MS);

  // 3 — the verdict lands: the aggregate strip and the instance-level trajectory line
  //     (rendered at trace close), straight from `belay verify --json`. Both are in
  //     the same viewport, so this is ONE beat — shooting them separately would be two
  //     near-identical frames spending the reader's attention on nothing.
  await page.waitForSelector('[data-testid="aggregate-strip"]', { timeout: VERDICT_TIMEOUT_MS });
  await page.waitForSelector('[data-testid="trajectory-line"]');
  await shoot(BEAT_MS);

  // 4 — the end of the run: the last turns, where the agent's edit is followed by the
  //     command turn that re-ran the suite — the evidence the trajectory line counts.
  await page.locator('[data-testid="turn-row"]').last().scrollIntoViewIfNeeded();
  await shoot(BEAT_MS);

  // 5 — one turn opened: the sub-verdicts behind the reduced status, and the coverage
  //     boundary that must travel with a PASS.
  const first = page.locator('[data-testid="turn-row"]').first();
  await first.locator(".turn-toggle").click();
  await first.scrollIntoViewIfNeeded();
  await shoot(FINAL_BEAT_MS);

  if (frames.length > MAX_FRAMES) fail(`${frames.length} frames exceeds the ${MAX_FRAMES}-frame budget.`);
  return frames;
}

/**
 * Decode the PNGs and encode the GIF inside the page.
 *
 * The browser is the only PNG decoder in reach without adding an image dependency to
 * node, and gifenc is pure JS, so both ends run there: small base64 PNGs in, one small
 * base64 GIF out. gifenc's dist is CJS, so it is evaluated behind a `module.exports`
 * shim rather than imported.
 */
async function encode(page, frames) {
  const gifencSource = readFileSync(path.join(CONSOLE_DIR, "node_modules", "gifenc", "dist", "gifenc.js"), "utf8");
  await page.goto("about:blank");
  await page.evaluate((source) => {
    const module = { exports: {} };
    new Function("module", "exports", source)(module, module.exports);
    window.__gifenc = module.exports;
  }, gifencSource);

  const base64 = await page.evaluate(async (input) => {
    const { GIFEncoder, quantize, applyPalette } = window.__gifenc;
    const gif = GIFEncoder();
    let width = 0;
    let height = 0;
    for (const frame of input.frames) {
      const image = new Image();
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("frame did not decode"));
        image.src = `data:image/png;base64,${frame.png}`;
      });
      width = image.naturalWidth;
      height = image.naturalHeight;
      const canvas = Object.assign(document.createElement("canvas"), { width, height });
      const ctx = canvas.getContext("2d");
      ctx.drawImage(image, 0, 0);
      const { data } = ctx.getImageData(0, 0, width, height);
      // The console is flat UI (a handful of greys plus the four verdict colours), so
      // a sub-256 palette is close to lossless and keeps the asset small.
      const palette = quantize(data, input.paletteSize);
      gif.writeFrame(applyPalette(data, palette), width, height, { palette, delay: frame.delay });
    }
    gif.finish();
    const bytes = gif.bytes();
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
  }, { frames, paletteSize: PALETTE_SIZE });

  return Buffer.from(base64, "base64");
}

await main();
