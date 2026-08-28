<script setup lang="ts">
// TraceView — every turn of one trace: derived facts from the trace, verdicts
// from the engine (`belay verify --json`), the aggregate strip, the coverage
// block, the FAIL diffs, and replay-from-here.

import { computed, onMounted, ref } from "vue";
import type {
  EngineError,
  TraceView,
  VerdictTurn,
  VerifyJsonDoc,
} from "../server/types";
import ReplayDialog from "./ReplayDialog.vue";
import TurnRow from "./TurnRow.vue";
import type { CoverageEntry } from "./CoverageLine.vue";
import VerdictBadge from "./VerdictBadge.vue";
import { useClicks } from "../useClicks";

const props = defineProps<{
  tracePath: string;
}>();

const emit = defineEmits<{
  back: [];
}>();

const view = ref<TraceView | null>(null);
const doc = ref<VerifyJsonDoc | null>(null);
const engineError = ref<EngineError | null>(null);
const loadError = ref<string | null>(null);
const replayTurn = ref<TraceView["turns"][number] | null>(null);
const { track } = useClicks();

onMounted(async () => {
  try {
    const viewRes = await fetch(`/api/trace?path=${encodeURIComponent(props.tracePath)}`, { cache: "no-store" });
    if (!viewRes.ok) {
      loadError.value = `trace load failed (${viewRes.status})`;
      return;
    }
    view.value = (await viewRes.json()).view as TraceView;
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
    return;
  }

  try {
    const verifyRes = await fetch("/api/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ trace: props.tracePath }),
    });
    const body = (await verifyRes.json()) as
      | { ok: true; doc: VerifyJsonDoc }
      | { ok: false; error: EngineError };
    if (body.ok) {
      doc.value = body.doc;
    } else {
      engineError.value = body.error;
    }
  } catch (e) {
    engineError.value = { cause: "spawn-failed", detail: e instanceof Error ? e.message : String(e) };
  }
});

const coverageEntries = computed<CoverageEntry[] | null>(() => {
  if (doc.value === null) return null;
  return Object.entries(doc.value.coverage).map(([dimension, block]) => ({ dimension, block }));
});

const turns = computed(() => view.value?.turns ?? []);

// The trace list hands over ABSOLUTE paths (the API resolves them inside the trace
// dir), so heading with the raw prop prints the operator's home directory. The name
// is what identifies a run; the full path stays reachable as the title.
const traceName = computed(() => props.tracePath.split("/").pop() || props.tracePath);

const verdictByOrdinal = computed(() => {
  const map = new Map<number, VerdictTurn>();
  for (const turn of doc.value?.turns ?? []) map.set(turn.ordinal, turn);
  return map;
});

function openReplay(turn: TraceView["turns"][number]): void {
  track("open-replay", props.tracePath, turn.ordinal);
  replayTurn.value = turn;
}

function onExpand(turn: TraceView["turns"][number]): void {
  track("expand", props.tracePath, turn.ordinal);
}
</script>

<template>
  <section class="trace-view">
    <header class="trace-head">
      <button type="button" class="back-btn" @click="emit('back')">← all traces</button>
      <h2 class="trace-name" :title="tracePath">{{ traceName }}</h2>
      <div v-if="doc" class="aggregate-strip" data-testid="aggregate-strip">
        <VerdictBadge status="PASS" /> <span class="agg-num">{{ doc.aggregate.PASS }}</span>
        <VerdictBadge status="WARN" /> <span class="agg-num">{{ doc.aggregate.WARN }}</span>
        <VerdictBadge status="FAIL" /> <span class="agg-num">{{ doc.aggregate.FAIL }}</span>
        <VerdictBadge status="UNVERIFIED" /> <span class="agg-num">{{ doc.aggregate.UNVERIFIED }}</span>
        <span class="agg-verified">{{ doc.aggregate.turns_verified }} turns verified</span>
      </div>
      <div v-if="doc && doc.trajectory" class="trajectory-line" data-testid="trajectory-line">
        <VerdictBadge :status="doc.trajectory.status" :cause="doc.trajectory.cause ?? null" />
        <span class="traj-message">{{ doc.trajectory.message }}</span>
      </div>
      <VerdictBadge v-else-if="engineError" status="no-engine" />
    </header>

    <p v-if="loadError" class="load-error">trace load failed: {{ loadError }}</p>
    <p v-if="engineError" class="engine-unavailable" data-testid="engine-unavailable">
      engine unavailable ({{ engineError.cause }}{{ engineError.detail ? `: ${engineError.detail}` : "" }}) —
      turns render without verdicts, never as PASS
    </p>
    <p v-else-if="view && doc === null" class="engine-pending">verifying…</p>

    <ol class="turn-list">
      <li v-for="turn in turns" :key="turn.ordinal">
        <TurnRow
          :turn="turn"
          :verdict="verdictByOrdinal.get(turn.ordinal) ?? null"
          :engine-error="engineError"
          :coverage="coverageEntries"
          @replay="openReplay"
          @expand="onExpand"
        />
      </li>
    </ol>

    <ReplayDialog
      v-if="replayTurn !== null"
      :trace="tracePath"
      :turn="replayTurn"
      @close="replayTurn = null"
    />
  </section>
</template>

<style scoped>
.trace-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.back-btn {
  font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 3px 8px;
  cursor: pointer;
}
.trace-name {
  font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace;
  margin: 0;
}
.aggregate-strip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  margin-left: auto;
}
.agg-num {
  margin-right: 6px;
}
.agg-verified {
  color: #64748b;
  font-weight: 500;
}
.trajectory-line {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  padding: 3px 8px;
  border: 1px solid #bbf7d0;
  border-radius: 4px;
  background: #f0fdf4;
}
.trajectory-line .traj-message {
  color: #334155;
}
.engine-unavailable,
.load-error {
  color: #991b1b;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.engine-pending {
  color: #64748b;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.turn-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>