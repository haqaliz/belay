<script setup lang="ts">
// The console shell: feed (live streaming) or trace view (per-turn verdicts).

import { ref } from "vue";
import FeedView from "./components/FeedView.vue";
import TraceView from "./components/TraceView.vue";

type View = { kind: "feed" } | { kind: "trace"; path: string };

const view = ref<View>({ kind: "feed" });

function openTrace(path: string): void {
  view.value = { kind: "trace", path };
}

function backToFeed(): void {
  view.value = { kind: "feed" };
}
</script>

<template>
  <div class="app">
    <header class="app-head">
      <h1>belay <span class="app-console">console</span></h1>
      <p class="app-tag">verdicts are grounded in replay, never in a judge's guess</p>
    </header>
    <main>
      <FeedView v-if="view.kind === 'feed'" @open-trace="openTrace" />
      <TraceView v-else :trace-path="view.path" @back="backToFeed" />
    </main>
  </div>
</template>

<style scoped>
.app {
  max-width: 860px;
  margin: 0 auto;
  padding: 18px 20px 60px;
}
.app-head {
  border-bottom: 2px solid #0f172a;
  margin-bottom: 14px;
}
.app-head h1 {
  margin: 0;
  font: 800 20px ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 0.02em;
}
.app-console {
  color: #1d4ed8;
}
.app-tag {
  margin: 2px 0 8px;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #64748b;
}
</style>