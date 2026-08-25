// useClicks: the local click/expand log. Every user click (expand a diff, open
// a trace, replay a turn) appends exactly ONE JSONL record to
// ~/.belay/console-events.jsonl via POST /api/events — on-box only. The clock
// and the transport are injectable; an unwritable log degrades silently in the
// UI (the server records the failure once in its own log), never a crash.

import { ref } from "vue";
import type { Ref } from "vue";

export interface ClickEvent {
  trace: string;
  turn: number | null;
  kind: string;
  t: string;
}

export interface ClickOptions {
  post?: (record: ClickEvent) => Promise<unknown>;
  now?: () => Date;
  onFailure?: (error: unknown) => void;
}

export interface ClickTracker {
  track: (kind: string, trace: string, turn: number | null) => void;
  /** Failures observed (exposed for tests); the UI degrades silently. */
  failures: Ref<number>;
}

export function useClicks(options: ClickOptions = {}): ClickTracker {
  const post =
    options.post ??
    ((record: ClickEvent) =>
      fetch("/api/events", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(record),
      }));
  const now = options.now ?? (() => new Date());
  const onFailure = options.onFailure ?? (() => {});
  const failures = ref(0);

  function track(kind: string, trace: string, turn: number | null): void {
    const record: ClickEvent = { trace, turn, kind, t: now().toISOString() };
    post(record).catch((error: unknown) => {
      failures.value += 1;
      onFailure(error);
    });
  }

  return { track, failures };
}