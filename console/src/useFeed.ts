// useFeed: polls the server's tail endpoint (/api/feed) and exposes the
// derived turns, the pending (partial) line, and the cursor. The clock and
// the fetch function are injectable — no Date.now and no global fetch in
// tested paths.

import { onUnmounted, ref } from "vue";
import type { Ref } from "vue";
import type { DerivedTurn, TraceView } from "./server/types";

export interface FeedState {
  turns: Ref<DerivedTurn[]>;
  pending: Ref<string | null>;
  cursor: Ref<number>;
  error: Ref<string | null>;
  windows: Ref<{ open: boolean; close: boolean }>;
  pollNow: () => void;
  stop: () => void;
}

export interface FeedOptions {
  pollMs?: number;
  now?: () => number;
  fetchFn?: typeof fetch;
}

interface FeedResponse {
  cursor: number;
  pending: string | null;
  turns: DerivedTurn[];
  windows: { open: boolean; close: boolean };
  error?: { cause: string };
}

export function useFeed(path: Ref<string | null>, options: FeedOptions = {}): FeedState {
  const pollMs = options.pollMs ?? 1000;
  const now = options.now ?? (() => Date.now());
  const fetchFn = options.fetchFn ?? ((...args: Parameters<typeof fetch>) => fetch(...args));

  const turns = ref<DerivedTurn[]>([]);
  const pending = ref<string | null>(null);
  const cursor = ref(0);
  const error = ref<string | null>(null);
  const windows = ref<TraceView["windows"]>({ open: false, close: false });

  let timer: ReturnType<typeof setTimeout> | null = null;
  let inFlight = false;
  let stopped = false;

  async function pollNow(): Promise<void> {
    if (inFlight || stopped) return;
    const target = path.value;
    if (target === null) {
      turns.value = [];
      pending.value = null;
      return;
    }
    inFlight = true;
    try {
      const response = await fetchFn(
        `/api/feed?path=${encodeURIComponent(target)}&cursor=${cursor.value}`,
        { cache: "no-store" },
      );
      const body = (await response.json()) as FeedResponse;
      if (body.error !== undefined) {
        error.value = body.error.cause;
        return;
      }
      error.value = null;
      cursor.value = body.cursor;
      pending.value = body.pending;
      turns.value = body.turns;
      windows.value = body.windows;
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      inFlight = false;
    }
  }

  function schedule(): void {
    if (stopped) return;
    const deadline = now() + pollMs;
    timer = setTimeout(() => {
      void pollNow().then(schedule);
    }, Math.max(0, deadline - now()));
  }

  function stop(): void {
    stopped = true;
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  onUnmounted(stop);
  void pollNow();
  schedule();

  return { turns, pending, cursor, error, windows, pollNow, stop };
}