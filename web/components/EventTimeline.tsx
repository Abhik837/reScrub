"use client";

import { formatTimestamp } from "@/lib/format";
import type { Finding } from "@/lib/types";
import { markerClass, statusLabel, uncertaintyLabel } from "./findingStyles";

interface EventTimelineProps {
  findings: Finding[];
  duration: number;
  currentTime: number;
  selectedId: string | null;
  onSelect: (eventId: string) => void;
  onSeek: (seconds: number) => void;
}

const LEGEND = [
  { swatch: "bg-flag-mark", label: "Needs review" },
  { swatch: "bg-amber-mark", label: "High uncertainty" },
  { swatch: "bg-ink", label: "Confirmed" },
  { swatch: "bg-line-strong", label: "Dismissed" },
];

export function EventTimeline({
  findings,
  duration,
  currentTime,
  selectedId,
  onSelect,
  onSeek,
}: EventTimelineProps) {
  const total = duration > 0 ? duration : 1;
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / total) * 100))}%`;

  return (
    <section aria-labelledby="timeline-heading" className="rounded-[3px] border border-line bg-surface px-4 pb-3 pt-3.5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="timeline-heading" className="eyebrow text-ink">
          Timeline
        </h2>
        <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Marker legend">
          {LEGEND.map((l) => (
            <li key={l.label} className="eyebrow flex items-center gap-1.5 text-ink-faint">
              <span className={`size-2 ${l.swatch}`} aria-hidden="true" /> {l.label}
            </li>
          ))}
        </ul>
      </div>

      <div className="relative h-14">
        {/* Base track with quarter ticks */}
        <div className="absolute inset-x-0 top-[26px] h-[2px] bg-line" />
        {[0.25, 0.5, 0.75].map((q) => (
          <div key={q} aria-hidden="true" className="absolute top-[22px] h-[10px] w-px bg-line-strong" style={{ left: `${q * 100}%` }} />
        ))}
        {/* Played portion */}
        <div className="absolute left-0 top-[26px] h-[2px] bg-ink" style={{ width: pct(currentTime) }} />

        {/* Finding ranges (start → end) */}
        {findings.map((f) =>
          f.endSec != null ? (
            <div
              key={`range-${f.eventId}`}
              aria-hidden="true"
              className={`absolute top-[21px] h-[12px] ${f.eventId === selectedId ? "bg-accent/20" : "bg-ink/[0.06]"}`}
              style={{ left: pct(f.timestampSec), width: `calc(${pct(f.endSec)} - ${pct(f.timestampSec)})` }}
            />
          ) : null,
        )}

        {/* Scrubber: an accessible range input stretched over the track. */}
        <input
          type="range"
          className="scrubber absolute inset-x-0 top-[12px] h-8 w-full"
          min={0}
          max={total}
          step={0.1}
          value={Math.min(currentTime, total)}
          onChange={(e) => onSeek(Number(e.target.value))}
          aria-label="Seek video"
          aria-valuetext={formatTimestamp(currentTime)}
        />

        {/* Playhead */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-[6px] h-[42px] w-[2px] -translate-x-1/2 bg-accent"
          style={{ left: pct(currentTime) }}
        />

        {/* Finding markers */}
        {findings.map((f, i) => {
          const selected = f.eventId === selectedId;
          return (
            <button
              key={f.eventId}
              type="button"
              onClick={() => onSelect(f.eventId)}
              aria-pressed={selected}
              aria-label={`Finding ${i + 1} at ${formatTimestamp(f.timestampSec)}: ${f.title}. ${statusLabel[f.reviewStatus]}, ${uncertaintyLabel[f.uncertainty.level].toLowerCase()}.`}
              className={`absolute top-0 flex size-6 -translate-x-1/2 items-center justify-center rounded-[2px] font-mono text-[11px] font-semibold ${markerClass(f)} ${
                selected ? "outline-2 outline-offset-2 outline-accent" : "hover:outline-1 hover:outline-offset-1 hover:outline-ink"
              } ${f.reviewStatus === "dismissed" ? "line-through" : ""}`}
              style={{ left: pct(f.timestampSec) }}
            >
              {i + 1}
            </button>
          );
        })}
      </div>

      <div className="tabular flex justify-between font-mono text-[11px] text-ink-faint">
        <span>00:00.0</span>
        <span>{formatTimestamp(duration)}</span>
      </div>
    </section>
  );
}
