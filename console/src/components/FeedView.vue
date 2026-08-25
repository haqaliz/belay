<script setup lang="ts">
// FeedView — the live feed: traces under the trace dir, one selected for
// streaming via the tail endpoint. The aggregate strip is honest by
// construction: verdicts only exist after an engine run (TraceView), so the
// live strip counts turns/tools/pending and never invents statuses.

import { onMounted, ref } from "vue";
import type { DerivedTurn } from "../server/types";
import { useClicks } from "../useClicks";
import { useFeed } from "../useFeed";

const emit = defineEmits<{
  openTrace: [path: string];
}>();

interface Listing {
  name: string;
  path: string;
  size: number;
  mtime: string;
  turns: number;
}

const traces = ref<Listing[]>([]);
const listError = ref<string | null>(null);
const selected = ref<string | null>(null);
const { track } = useClicks();

const { turns, pending, error, windows } = useFeed(selected, { pollMs: 750 });

onMounted(async () => {
  try {
    const res = await fetch("/api/traces", { cache: "no-store" });
    const body = (await res.json()) as { traces: Listing[] };
    traces.value = body.traces;
    if (traces.value.length > 0) {
      // the most recently modified trace is the live one
      selected.value = [...traces.value].sort((a, b) => (a.mtime < b.mtime ? 1 : -1))[0].path;
    }
  } catch (e) {
    listError.value = e instanceof Error ? e.message : String(e);
  }
});

function open(turn: DerivedTurn): void {
  if (selected.value === null) return;
  track("open-trace", selected.value, turn.ordinal);
  emit("openTrace", selected.value);
}

function selectTrace(path: string): void {
  selected.value = path;
}
</script>

<template>
  <section class="feed-view">
    <header class="feed-head">
      <h2>live feed</h2>
      <div class="feed-strip" data-testid="feed-strip">
        <span class="strip-item"><strong>{{ turns.length }}</strong> turns</span>
        <span v-if="pending" class="strip-item strip-pending" data-testid="pending-line">pending line…</span>
        <span v-if="!windows.close" class="strip-item strip-live">recording</span>
        <span v-else class="strip-item strip-closed">window closed</span>
        <span v-if="error" class="strip-item strip-error">{{ error }}</span>
      </div>
    </header>

    <p v-if="listError" class="feed-error">trace list failed: {{ listError }}</p>

    <div class="trace-picker">
      <button
        v-for="t in traces"
        :key="t.path"
        type="button"
        class="trace-pill"
        :class="{ selected: selected === t.path }"
        :title="`${t.turns} turns · ${t.size} bytes`"
        @click="selectTrace(t.path)"
      >
        {{ t.name }}
      </button>
      <span v-if="traces.length === 0" class="no-traces">
        no traces under {{ selected === null ? "the trace dir" : "…" }} — capture a run with BELAY_TRACE_DIR set
      </span>
    </div>

    <ol class="feed-list">
      <li v-for="turn in turns" :key="turn.ordinal" class="feed-row" @click="open(turn)">
        <span class="feed-ordinal">t{{ turn.ordinal }}</span>
        <span class="feed-tool">{{ turn.tool }}</span>
        <span class="feed-time">{{ turn.t_in }}</span>
      </li>
    </ol>
    <p v-if="selected !== null && pending" class="pending-note">
      a partial line is being written — it stays pending until its newline arrives, never a turn
    </p>
  </section>
</template>

<style scoped>
.feed-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.feed-head h2 {
  margin: 0;
  font: 700 15px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.feed-strip {
  display: inline-flex;
  gap: 10px;
  align-items: center;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #475569;
  margin-left: auto;
}
.strip-pending {
  color: #92400e;
  font-style: italic;
}
.strip-live {
  color: #14532d;
}
.strip-closed {
  color: #64748b;
}
.strip-error {
  color: #991b1b;
}
.feed-error {
  color: #991b1b;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.trace-picker {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 8px 0;
}
.trace-pill {
  font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 2px 10px;
  cursor: pointer;
}
.trace-pill.selected {
  background: #1d4ed8;
  border-color: #1d4ed8;
  color: #ffffff;
}
.no-traces {
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #64748b;
}
.feed-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.feed-row {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}
.feed-row:hover {
  background: #f1f5f9;
}
.feed-ordinal {
  font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #64748b;
}
.feed-tool {
  font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.feed-time {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #94a3b8;
  margin-left: auto;
}
.pending-note {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #92400e;
  font-style: italic;
}
</style>