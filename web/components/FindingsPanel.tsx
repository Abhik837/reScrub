"use client";

import { useEffect, useRef, useState } from "react";
import type { Finding, ReviewStatus } from "@/lib/types";
import { FindingDetail } from "./FindingDetail";

type Filter = "all" | ReviewStatus | "uncertain";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "needs_review", label: "Needs review" },
  { value: "confirmed", label: "Confirmed" },
  { value: "dismissed", label: "Dismissed" },
  { value: "uncertain", label: "High uncertainty" },
];

function matches(f: Finding, filter: Filter) {
  if (filter === "all") return true;
  if (filter === "uncertain") return f.uncertainty.level === "high";
  return f.reviewStatus === filter;
}

interface FindingsPanelProps {
  /** All findings, sorted by time. Numbers match the timeline markers. */
  findings: Finding[];
  selectedId: string | null;
  currentTime: number;
  /** Event IDs that have a decision which can be undone. */
  undoable: Set<string>;
  onSelect: (eventId: string) => void;
  onDecide: (eventId: string, status: ReviewStatus) => void;
  onUndo: (eventId: string) => void;
}

export function FindingsPanel({
  findings,
  selectedId,
  currentTime,
  undoable,
  onSelect,
  onDecide,
  onUndo,
}: FindingsPanelProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const listRef = useRef<HTMLDivElement>(null);
  const visible = findings.filter((f) => matches(f, filter));

  // When a finding is chosen (e.g. from the timeline), scroll it into view inside
  // the panel only. The page itself does not jump.
  useEffect(() => {
    const list = listRef.current;
    if (!list || !selectedId || list.scrollHeight <= list.clientHeight) return;
    const card = list.querySelector<HTMLElement>(`#finding-${CSS.escape(selectedId)}`);
    if (!card) return;
    const top = card.offsetTop; // the list is position:relative, so this is relative to it
    if (top < list.scrollTop || top + card.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top - 8;
    }
  }, [selectedId]);

  return (
    <section
      aria-labelledby="findings-heading"
      className="flex max-h-[75vh] flex-col rounded-[3px] border border-line bg-canvas lg:max-h-[calc(100vh-3rem)]"
    >
      <div className="border-b border-line bg-surface px-4 pt-3.5">
        <h2 id="findings-heading" className="eyebrow text-ink">
          Findings <span className="text-ink-faint">· {findings.length}</span>
        </h2>
        {/* Filter tabs with an underline for the active one */}
        <div role="group" aria-label="Filter findings" className="-mb-px mt-2 flex flex-wrap gap-x-4">
          {FILTERS.map(({ value, label }) => {
            const count = findings.filter((f) => matches(f, value)).length;
            const active = filter === value;
            return (
              <button
                key={value}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(value)}
                className={`min-h-9 border-b-2 text-[13px] transition-colors ${
                  active ? "border-ink font-medium text-ink" : "border-transparent text-ink-muted hover:text-ink"
                }`}
              >
                {label} <span className="tabular font-mono text-[11px] text-ink-faint">{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div ref={listRef} className="relative flex-1 space-y-3 overflow-y-auto p-3">
        {findings.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-ink-muted">
            The analysis returned no findings for this recording. That does not mean no breaches
            occurred; watch the recording to check.
          </p>
        ) : visible.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-ink-muted">No findings match this filter.</p>
        ) : (
          visible.map((f) => (
            <FindingDetail
              key={f.eventId}
              finding={f}
              number={findings.indexOf(f) + 1}
              selected={f.eventId === selectedId}
              inView={currentTime >= f.timestampSec && currentTime <= (f.endSec ?? f.timestampSec + 2)}
              canUndo={undoable.has(f.eventId)}
              onSelect={() => onSelect(f.eventId)}
              onDecide={(status) => onDecide(f.eventId, status)}
              onUndo={() => onUndo(f.eventId)}
            />
          ))
        )}
      </div>
    </section>
  );
}
