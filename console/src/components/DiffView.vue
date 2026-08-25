<script setup lang="ts">
// DiffView — a FAILed turn's diff, taken from the engine's sub-verdict
// messages (the console never diffs anything itself). Lines are rendered
// verbatim; `-`/`+`-prefixed lines get the deletion/addition treatment.

defineProps<{
  messages: string[];
}>();
</script>

<template>
  <div class="diff-view" data-testid="diff-view">
    <pre v-for="(message, i) in messages" :key="i" class="diff-message"><template
      v-for="(line, j) in message.split('\n')"
      :key="j"><span :class="line.startsWith('-') ? 'diff-del' : line.startsWith('+') ? 'diff-add' : 'diff-ctx'">{{
        line }}</span>
</template></pre>
  </div>
</template>

<style scoped>
.diff-view {
  margin: 6px 0;
}
.diff-message {
  margin: 0;
  padding: 6px 8px;
  background: #0f172a;
  border-radius: 4px;
  font: 500 12px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap;
  overflow-x: auto;
}
.diff-del {
  color: #fca5a5;
}
.diff-add {
  color: #86efac;
}
.diff-ctx {
  color: #cbd5e1;
}
</style>