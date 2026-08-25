<script setup lang="ts">
// ReplayDialog — replay-from-here. The console never invokes replay without
// context: the trace and the turn ordinal are recorded context, and the
// server/manifest inputs are REQUIRED for a real re-invocation. Missing
// context renders a named-cause UNVERIFIED, never a fabricated verdict and
// never a silent skip.

import { ref } from "vue";
import type { DerivedTurn, EngineError, VerifyJsonDoc } from "../server/types";
import VerdictBadge from "./VerdictBadge.vue";
import CoverageLine from "./CoverageLine.vue";
import type { CoverageEntry } from "./CoverageLine.vue";
import { useClicks } from "../useClicks";

const props = defineProps<{
  trace: string;
  turn: DerivedTurn;
}>();

const emit = defineEmits<{
  close: [];
}>();

type DialogState =
  | { state: "idle" }
  | { state: "running" }
  | { state: "unverified"; cause: string }
  | { state: "done"; doc: VerifyJsonDoc }
  | { state: "error"; error: EngineError };

const server = ref("");
const manifest = ref("");
const state = ref<DialogState>({ state: "idle" });
const { track } = useClicks();

const coverageEntries = (doc: VerifyJsonDoc): CoverageEntry[] =>
  Object.entries(doc.coverage).map(([dimension, block]) => ({ dimension, block }));

async function run(): Promise<void> {
  if (props.trace.length === 0) {
    state.value = { state: "unverified", cause: "missing-context: no trace recorded" };
    return;
  }
  if (server.value.trim().length === 0 || manifest.value.trim().length === 0) {
    state.value = {
      state: "unverified",
      cause: "missing-context: replay needs the server command and manifest dir that recorded this turn",
    };
    return;
  }
  track("replay", props.trace, props.turn.ordinal);
  state.value = { state: "running" };
  try {
    const res = await fetch("/api/replay", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        trace: props.trace,
        turn: props.turn.ordinal,
        server: server.value.trim(),
        manifest: manifest.value.trim(),
      }),
    });
    const body = (await res.json()) as
      | { ok: true; doc: VerifyJsonDoc }
      | { ok: false; error: EngineError };
    if (body.ok) {
      state.value = { state: "done", doc: body.doc };
    } else {
      state.value = { state: "error", error: body.error };
    }
  } catch (e) {
    state.value = {
      state: "error",
      error: { cause: "spawn-failed", detail: e instanceof Error ? e.message : String(e) },
    };
  }
}
</script>

<template>
  <div class="replay-overlay" data-testid="replay-dialog">
    <div class="replay-dialog" role="dialog" aria-label="replay turn">
      <header class="replay-head">
        <h3>replay — t{{ turn.ordinal }} {{ turn.tool }}</h3>
        <button type="button" class="close-btn" @click="emit('close')">×</button>
      </header>

      <p class="replay-context">trace: <code>{{ trace }}</code></p>

      <div v-if="state.state === 'idle' || state.state === 'running' || state.state === 'unverified'" class="replay-form">
        <label class="field">
          server command
          <input v-model="server" type="text" placeholder="python server.py" data-testid="server-input" />
        </label>
        <label class="field">
          manifest dir
          <input v-model="manifest" type="text" placeholder="/path/to/manifest" data-testid="manifest-input" />
        </label>
        <button type="button" class="run-btn" :disabled="state.state === 'running'" data-testid="run-btn" @click="run">
          {{ state.state === "running" ? "replaying…" : "replay this turn" }}
        </button>
      </div>

      <p v-if="state.state === 'unverified'" class="unverified-cause" data-testid="unverified-cause">
        <VerdictBadge status="UNVERIFIED" :cause="state.cause" />
        <span class="cause-text">{{ state.cause }}</span>
      </p>

      <div v-if="state.state === 'done'" class="replay-result" data-testid="replay-result">
        <VerdictBadge :status="state.doc.turns[0]?.status ?? 'UNVERIFIED'" :cause="state.doc.turns[0]?.cause ?? null" />
        <ul v-if="state.doc.turns[0]" class="replay-subverdicts">
          <li v-for="(sv, i) in state.doc.turns[0].sub_verdicts" :key="i" class="replay-sub">
            <VerdictBadge :status="sv.status" :cause="sv.cause ?? null" />
            <span class="sub-axis">{{ sv.axis }} · {{ sv.kind }}</span>
            <span class="sub-message">{{ sv.message }}</span>
          </li>
        </ul>
        <CoverageLine :coverage="coverageEntries(state.doc)" />
      </div>

      <p v-if="state.state === 'error'" class="replay-error" data-testid="replay-error">
        engine unavailable ({{ state.error.cause }}{{ state.error.detail ? `: ${state.error.detail}` : "" }})
      </p>
    </div>
  </div>
</template>

<style scoped>
.replay-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
}
.replay-dialog {
  width: min(640px, 90vw);
  background: #ffffff;
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.25);
}
.replay-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.replay-head h3 {
  margin: 0;
  font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.close-btn {
  border: 0;
  background: none;
  font-size: 18px;
  cursor: pointer;
  color: #64748b;
}
.replay-context {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #64748b;
}
.replay-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #475569;
}
.field input {
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  padding: 4px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
}
.run-btn {
  align-self: flex-start;
  font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #ffffff;
  background: #1d4ed8;
  border: 0;
  border-radius: 4px;
  padding: 5px 12px;
  cursor: pointer;
}
.run-btn:disabled {
  background: #93c5fd;
  cursor: wait;
}
.unverified-cause {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #1e293b;
}
.replay-result {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.replay-subverdicts {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.replay-sub {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.sub-axis {
  color: #475569;
}
.sub-message {
  color: #334155;
}
.replay-error {
  color: #991b1b;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>