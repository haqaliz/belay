<script setup lang="ts">
// VerdictBadge — THE honesty surface. UNVERIFIED is never grouped with PASS:
// every status gets its own class and its own label, and NOT_COVERED /
// no-engine render as distinct boundaries. The C7 correctness test asserts
// the UNVERIFIED-vs-PASS classes and labels differ.

import { computed } from "vue";
import type { RenderStatus } from "../server/types";

const props = defineProps<{
  status: RenderStatus;
  cause?: string | null;
}>();

const LABELS: Record<RenderStatus, string> = {
  PASS: "PASS",
  WARN: "WARN",
  FAIL: "FAIL",
  UNVERIFIED: "UNVERIFIED",
  NOT_COVERED: "NOT_COVERED",
  "no-engine": "NO ENGINE",
};

const label = computed(() => LABELS[props.status]);
const klass = computed(() => {
  const slug = props.status === "no-engine" ? "no-engine" : props.status.toLowerCase().replace(/_/g, "-");
  return `verdict-${slug}`;
});
</script>

<template>
  <span class="verdict-badge" :class="klass" :data-status="status" :title="cause ?? undefined">
    {{ label }}<span v-if="status === 'UNVERIFIED' && cause" class="verdict-cause"> · {{ cause }}</span>
  </span>
</template>

<style scoped>
.verdict-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  font: 700 11px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
/* every status is its own class — UNVERIFIED is never a "passed"/"ok" colour */
.verdict-pass {
  color: #14532d;
  background: #dcfce7;
  border: 1px solid #86efac;
}
.verdict-warn {
  color: #713f12;
  background: #fef3c7;
  border: 1px solid #fcd34d;
}
.verdict-fail {
  color: #7f1d1d;
  background: #fee2e2;
  border: 1px solid #fca5a5;
}
.verdict-unverified {
  color: #1e293b;
  background: #e2e8f0;
  border: 1px dashed #94a3b8;
}
.verdict-not-covered {
  color: #334155;
  background: #f1f5f9;
  border: 1px dotted #94a3b8;
}
.verdict-no-engine {
  color: #450a0a;
  background: #fecaca;
  border: 1px solid #f87171;
}
.verdict-cause {
  font-weight: 500;
}
</style>