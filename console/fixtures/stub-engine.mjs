#!/usr/bin/env node
// STUB `belay` binary for the console's server tests. NOT the real engine and
// no verdict logic: it reads its argv exactly like `belay verify --json` would
// (`--turn N` optional, trace path positional) and emits the pinned A1
// `verify --json` contract document that corresponds to the named trace
// (console/fixtures/verify-*.json). The real engine is built in parallel
// (aspect verify-json); the console's integration with it is proven by A1's
// own tests — this stub only proves the subprocess contract.
//
// Exit codes mirror the pinned contract: FAIL/UNVERIFIED traces exit non-zero,
// exactly as without --json (the console renders the verdicts anyway — exit
// code is not the error signal).
import { readFileSync } from "node:fs";

const argv = process.argv.slice(2);

const mode = process.env.STUB_ENGINE_MODE ?? null;
if (mode === "bad-json") {
  process.stdout.write("this is not the json contract\n");
  process.exit(1);
}
if (mode === "empty") {
  process.exit(1);
}
if (mode === "argv") {
  // Echo the argv as a JSON doc: the seam for "did the server pass X?" —
  // the timeout-passthrough tests read this instead of inferring from success.
  process.stdout.write(JSON.stringify({ schema: 1, argv }));
  process.exit(0);
}

const hasTurn = argv.includes("--turn");
// The trace is the FIRST positional after the `verify` subcommand:
// `verify`'s `--server` is REMAINDER, so everything after it belongs to the
// server command.
const positional = argv.slice(1).find((a) => !a.startsWith("-"));
const name = positional ?? "trace-clean.jsonl";

let doc = "verify-clean.json";
if (name.includes("failed")) doc = "verify-failed.json";
else if (name.includes("unverified")) doc = "verify-unverified.json";
if (hasTurn) doc = "verify-turn.json";
if (mode === "error") doc = "verify-error.json";

process.stdout.write(readFileSync(new URL(`./${doc}`, import.meta.url), "utf8"));
process.exit(doc === "verify-failed.json" || doc === "verify-unverified.json" || doc === "verify-error.json" ? 1 : 0);