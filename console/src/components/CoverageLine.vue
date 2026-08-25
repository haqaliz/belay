<script setup lang="ts">
// CoverageLine — the coverage block that must travel with every status on
// every surface. The engine ALWAYS emits the coverage block (even empty); an
// ABSENT block is a data gap and renders "coverage unavailable" — never
// fabricated, never silently dropped. A PASS rendered without its coverage
// line is the failure mode this component exists to prevent (enforced by the
// TurnRow/TraceView tests).

import type { CoverageBlock } from "../server/types";

export interface CoverageEntry {
  dimension: string;
  block: CoverageBlock;
}

const props = defineProps<{
  /** null = absent (never fabricated); [] = the engine's empty-but-present block. */
  coverage: CoverageEntry[] | null;
}>();
</script>

<template>
  <div class="coverage-line" data-testid="coverage-line">
    <template v-if="props.coverage === null">
      <span class="coverage-unavailable">coverage unavailable</span>
    </template>
    <template v-else-if="props.coverage.length === 0">
      <span class="coverage-empty">no dimensions outside the checked set</span>
    </template>
    <template v-else>
      <span v-for="entry in props.coverage" :key="entry.dimension" class="coverage-entry">
        <strong>{{ entry.dimension }}</strong>
        <span class="coverage-count">{{ entry.block.not_observed_turns }}/{{ entry.block.of_turns }} turns</span>
        <span class="coverage-message">{{ entry.block.message }}</span>
      </span>
    </template>
  </div>
</template>

<style scoped>
.coverage-line {
  margin-top: 2px;
  font: 500 11px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #475569;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.coverage-unavailable {
  color: #92400e;
  font-style: italic;
}
.coverage-empty {
  color: #64748b;
}
.coverage-entry {
  display: inline-flex;
  gap: 6px;
  flex-wrap: wrap;
}
.coverage-count {
  color: #0f172a;
}
.coverage-message {
  color: #64748b;
}
</style>