<script setup lang="ts">
// ApprovalPanel — the human side of the engine's file contract. It polls the
// pending holds, counts down to each deadline, and writes the decision file.
// It never claims a verdict: past the deadline the buttons die and the only
// text is the engine's own fail-closed rule.

import { onMounted, onUnmounted, ref } from "vue";
import type { ApprovalHold } from "../server/types";

const props = withDefaults(
  defineProps<{
    /** Injected like useFeed: no global fetch and no Date.now in tested paths. */
    fetchFn?: typeof fetch;
    now?: () => number;
    pollMs?: number;
  }>(),
  { pollMs: 1000 },
);

const fetchFn = props.fetchFn ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
const clockNow = props.now ?? (() => Date.now());

const configured = ref(false);
const holds = ref<ApprovalHold[]>([]);
const clock = ref(clockNow());
/** Two sources kept apart: a poll failure is transport, a refusal is the server's answer. */
const pollError = ref<string | null>(null);
const refusal = ref<string | null>(null);
const reasons = ref<Record<string, string>>({});

let timer: ReturnType<typeof setTimeout> | null = null;
let inFlight = false;
let stopped = false;

async function pollNow(): Promise<void> {
  if (inFlight || stopped) return;
  inFlight = true;
  try {
    const response = await fetchFn("/api/approvals", { cache: "no-store" });
    const body = (await response.json()) as { configured: boolean; holds: ApprovalHold[] };
    configured.value = body.configured;
    holds.value = body.holds ?? [];
    pollError.value = null;
  } catch (e) {
    pollError.value = e instanceof Error ? e.message : String(e);
  } finally {
    clock.value = clockNow();
    inFlight = false;
  }
}

async function decide(hold: ApprovalHold, decision: "approve" | "deny"): Promise<void> {
  const reason = (reasons.value[hold.hold_id] ?? "").trim();
  const body =
    decision === "deny" && reason.length > 0
      ? { hold_id: hold.hold_id, decision, reason }
      : { hold_id: hold.hold_id, decision };
  try {
    const response = await fetchFn("/api/approvals/decision", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.ok) {
      refusal.value = null;
    } else {
      const payload = (await response.json()) as { error?: { cause?: string } };
      refusal.value = payload.error?.cause ?? `http-${response.status}`;
    }
  } catch (e) {
    refusal.value = e instanceof Error ? e.message : String(e);
  }
  // Never optimistic: the next list is the server's, whatever the refusal was.
  await pollNow();
}

function remainingMs(hold: ApprovalHold): number {
  return Math.max(0, hold.expires_at * 1000 - clock.value);
}

function expired(hold: ApprovalHold): boolean {
  return remainingMs(hold) === 0;
}

function countdown(hold: ApprovalHold): string {
  return `expires in ${Math.ceil(remainingMs(hold) / 1000)}s`;
}

function schedule(): void {
  if (stopped) return;
  timer = setTimeout(() => {
    clock.value = clockNow(); // the countdown moves even while a poll is in flight
    void pollNow().then(schedule);
  }, props.pollMs);
}

function stop(): void {
  stopped = true;
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

onMounted(() => {
  void pollNow();
  schedule();
});
onUnmounted(stop);
</script>

<template>
  <section v-if="configured" class="approval-panel" data-testid="approval-panel">
    <header class="approval-head">
      <h2>approval holds</h2>
      <span class="approval-note">the engine is waiting on a human — a denied call is an observation</span>
    </header>
    <p v-if="refusal ?? pollError" class="approval-error" data-testid="approval-error">{{ refusal ?? pollError }}</p>
    <p v-if="holds.length === 0" class="approval-empty" data-testid="approval-empty">no holds are pending</p>
    <ol class="approval-list">
      <li v-for="hold in holds" :key="hold.hold_id" class="approval-row" data-testid="approval-hold">
        <div class="approval-line">
          <span class="approval-tool" data-testid="approval-tool">{{ hold.tool }}</span>
          <span class="approval-triggers" data-testid="approval-triggers">{{ hold.triggers.join(", ") }}</span>
          <span class="approval-created" data-testid="approval-created" :title="hold.hold_id">
            created {{ new Date(hold.created_at * 1000).toISOString().slice(11, 19) }}z
          </span>
          <span v-if="!expired(hold)" class="approval-countdown" data-testid="approval-countdown">{{ countdown(hold) }}</span>
          <span v-else class="approval-timeout" data-testid="approval-timeout">timed out — the engine fails closed</span>
        </div>
        <div class="approval-actions">
          <input
            v-model="reasons[hold.hold_id]"
            class="approval-reason"
            data-testid="deny-reason"
            type="text"
            placeholder="reason (deny only)"
            :disabled="expired(hold)"
          />
          <button type="button" class="approval-approve" data-testid="approve-btn" :disabled="expired(hold)" @click="decide(hold, 'approve')">
            approve
          </button>
          <button type="button" class="approval-deny" data-testid="deny-btn" :disabled="expired(hold)" @click="decide(hold, 'deny')">
            deny
          </button>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.approval-panel {
  margin: 8px 0 14px;
  padding: 8px 10px;
  border: 1px solid #fcd34d;
  border-radius: 6px;
  background: #fffbeb;
}
.approval-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.approval-head h2 {
  margin: 0;
  font: 700 15px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #92400e;
}
.approval-note {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #92400e;
}
.approval-error {
  margin: 6px 0 0;
  color: #991b1b;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.approval-empty {
  margin: 6px 0 0;
  color: #64748b;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.approval-list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.approval-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 8px;
  border: 1px solid #fde68a;
  border-radius: 4px;
  background: #ffffff;
}
.approval-line {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
}
.approval-tool {
  font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.approval-triggers {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #92400e;
}
.approval-created {
  font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #94a3b8;
}
.approval-countdown {
  margin-left: auto;
  font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #475569;
}
.approval-timeout {
  margin-left: auto;
  font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #991b1b;
}
.approval-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}
.approval-reason {
  flex: 1;
  min-width: 120px;
  font: 500 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  padding: 2px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
}
.approval-approve,
.approval-deny {
  font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace;
  border-radius: 4px;
  padding: 2px 10px;
  cursor: pointer;
}
.approval-approve {
  background: #14532d;
  border: 1px solid #14532d;
  color: #ffffff;
}
.approval-deny {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #991b1b;
}
.approval-approve:disabled,
.approval-deny:disabled,
.approval-reason:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
