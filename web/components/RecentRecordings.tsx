"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { cancelJob, isBackendConfigured, listRecordings } from "@/lib/api";
import type { RecordingSummary } from "@/lib/types";
import { buttonStyles } from "./ui";

const LABELS: Record<RecordingSummary["state"], string> = {
  queued: "Queued",
  analyzing: "Analyzing",
  completed: "Ready to review",
  failed: "Didn’t finish",
  canceled: "Canceled",
};

const running = (r: RecordingSummary) => r.state === "queued" || r.state === "analyzing";

function shortDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * The signed-in user's recent recordings, so a job started earlier (or hidden by a page refresh) can
 * be reopened or canceled. Refreshes itself while any of them is still queued or analyzing.
 */
export function RecentRecordings({ currentSessionId }: { currentSessionId: string | null }) {
  const [items, setItems] = useState<RecordingSummary[] | null>(null);
  const [canceling, setCanceling] = useState<string | null>(null);

  // The list is a convenience: if it can't be loaded, the rest of the page works without it.
  const load = useCallback(
    (signal?: AbortSignal) => listRecordings(signal).then(setItems, () => {}),
    [],
  );

  const anyRunning = items?.some(running) ?? false;
  useEffect(() => {
    if (!isBackendConfigured) return;
    const controller = new AbortController();
    load(controller.signal);
    const timer = anyRunning ? setInterval(() => load(controller.signal), 10_000) : undefined;
    return () => {
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [load, anyRunning, currentSessionId]);

  if (!items || items.length === 0) return null;

  async function cancel(id: string) {
    setCanceling(id);
    try {
      await cancelJob(id);
    } catch {
      // Shown by the next refresh of the list.
    } finally {
      setCanceling(null);
      load();
    }
  }

  return (
    <section aria-labelledby="recordings-heading" className="mb-8">
      <h2 id="recordings-heading" className="font-display text-[26px] leading-tight tracking-[-0.01em]">
        Your recordings
      </h2>
      <ul className="mt-4 divide-y divide-line border-y border-line text-[15px]">
        {items.slice(0, 8).map((r) => (
          <li key={r.sessionId} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-3">
            <div className="min-w-0">
              <Link
                href={`/review?session=${encodeURIComponent(r.sessionId)}`}
                className="block truncate font-medium text-ink underline-offset-4 hover:underline"
                aria-current={r.sessionId === currentSessionId ? "page" : undefined}
              >
                {r.name}
              </Link>
              <span className="text-[13px] text-ink-muted">
                {LABELS[r.state]}
                {r.state === "analyzing" && r.progress > 0 && ` · ${Math.round(r.progress * 100)}%`}
                {shortDate(r.createdAt) && ` · ${shortDate(r.createdAt)}`}
              </span>
            </div>
            {running(r) && (
              <button
                type="button"
                className={buttonStyles.small}
                disabled={canceling === r.sessionId}
                onClick={() => cancel(r.sessionId)}
              >
                {canceling === r.sessionId ? "Canceling…" : "Cancel"}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
