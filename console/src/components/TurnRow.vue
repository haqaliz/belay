<script setup lang="ts">
// TurnRow — one derived turn plus its engine verdict. Every surface renders
// status AND coverage line: a PASS without its coverage line is the failure
// mode (enforced by test). A FAILed turn shows its diff (from the sub-verdict
// messages). The no-engine state renders "NO ENGINE", distinct from PASS and
// from UNVERIFIED.

import { computed, ref } from "vue";
import type { DerivedTurn, EngineError, SubVerdict, VerdictTurn } from "../server/types";
import CoverageLine from "./CoverageLine.vue";
import type { CoverageEntry } from "./CoverageLine.vue";
import DiffView from "./DiffView.vue";
import VerdictBadge from "./VerdictBadge.vue";

const props = defineProps<{
  turn: DerivedTurn;
  verdict: VerdictTurn | null;
  engineError: EngineError | null;
  coverage: CoverageEntry[] | null;
}>();

const emit = defineEmits<{
  replay: [turn: DerivedTurn];
  expand: [turn: DerivedTurn];
}>();

const expanded = ref(false);

const status = computed<"PASS" | "WARN" | "FAIL" | "UNVERIFIED" | "NOT_COVERED" | "no-engine" | "pending">(() => {
  if (props.verdict !== null) return props.verdict.status;
  if (props.engineError !== null) return "no-engine";
  return "pending";
});

const failMessages = computed(() =>
  (props.verdict?.sub_verdicts ?? [])
    .filter((s: SubVerdict) => s.status === "FAIL")
    .map((s: SubVerdict) => s.message),
);

const subVerdicts = computed(() => props.verdict?.sub_verdicts ?? []);

const argsText = computed(() => safeJson(props.turn.args));
const resultText = computed(() => safeJson(props.turn.result));

function safeJson(value: unknown): string {
  if (value === null || value === undefined) return "(none)";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function toggle(): void {
  expanded.value = !expanded.value;
  emit("expand", props.turn);
}

function badges(): SubVerdict[] {
  return subVerdicts.value.filter((s) => s.status === "FAIL" || s.status === "UNVERIFIED" || s.status === "NOT_COVERED");
}
</script>

<template>
  <article class="turn-row" :data-status="status" data-testid="turn-row">
    <header class="turn-head">
      <button class="turn-toggle" type="button" :aria-expanded="expanded" @click="toggle">
        <span class="turn-ordinal">t{{ turn.ordinal }}</span>
        <span class="turn-tool">{{ turn.tool }}</span>
      </button>
      <span class="turn-time">{{ turn.t_in }}</span>
      <VerdictBadge v-if="status !== 'pending'" :status="status" :cause="verdict?.cause ?? null" />
      <span v-else class="turn-pending">verifying…</span>
      <button class="replay-btn" type="button" @click.stop="emit('replay', turn)">replay</button>
    </header>

    <CoverageLine :coverage="coverage" />

    <ul v-if="badges().length > 0" class="sub-verdicts">
      <li v-for="(sv, i) in badges()" :key="i" class="sub-verdict" :data-kind="sv.kind">
        <VerdictBadge :status="sv.status" :cause="sv.cause ?? null" />
        <span class="sub-axis">{{ sv.axis }} · {{ sv.kind }}</span>
        <span class="sub-message">{{ sv.message }}</span>
      </li>
    </ul>

    <DiffView v-if="status === 'FAIL' && failMessages.length > 0" :messages="failMessages" />

    <div v-if="expanded" class="turn-detail">
      <details class="args" open>
        <summary>args</summary>
        <pre>{{ argsText }}</pre>
      </details>
      <details class="result">
        <summary>result</summary>
        <pre>{{ resultText }}</pre>
      </details>
      <dl v-if="turn.annotations" class="annotations">
        <dt>annotations</dt>
        <dd>
          <span v-for="(ann, key) in turn.annotations.annotations" :key="key" class="annotation">
            {{ key }}: <strong>{{ ann.state }}</strong>
          </span>
        </dd>
      </dl>
      <dl v-if="turn.stateHandle.status !== 'absent'" class="state-handle">
        <dt>state handle</dt>
        <dd>{{ turn.stateHandle.status }}<template v-if="turn.stateHandle.cause"> · {{ turn.stateHandle.cause }}</template></dd>
      </dl>
    </div>
  </article>
</template>

<style scoped>
.turn-row {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 10px;
  background: #ffffff;
}
.turn-row[data-status="FAIL"] {
  border-color: #fca5a5;
}
.turn-row[data-status="UNVERIFIED"] {
  border-style: dashed;
  border-color: #94a3b8;
}
.turn-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.turn-toggle {
  display: inline-flex;
  gap: 8px;
  align-items: baseline;
  border: 0;
  background: none;
  padding: 0;
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.turn-ordinal {
  font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #64748b;
}
.turn-tool {
  font: 700 13px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #0f172a;
}
.turn-time {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #94a3b8;
  margin-left: auto;
}
.turn-pending {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #64748b;
  font-style: italic;
}
.replay-btn {
  font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 3px;
  padding: 1px 8px;
  cursor: pointer;
}
.sub-verdicts {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.sub-verdict {
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
.turn-detail {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.turn-detail pre {
  margin: 2px 0;
  padding: 6px 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font: 500 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap;
  max-height: 200px;
  overflow: auto;
}
.turn-detail dl {
  margin: 2px 0;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.turn-detail dt {
  color: #64748b;
}
.annotations dd {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 2px 0 0;
}
.annotation {
  color: #334155;
}
</style>