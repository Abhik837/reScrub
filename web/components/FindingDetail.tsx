"use client";

import { formatTimestamp } from "@/lib/format";
import type { Finding, ReviewStatus } from "@/lib/types";
import {
  markerClass,
  statusChip,
  statusDot,
  statusEdge,
  statusLabel,
  uncertaintyChip,
  uncertaintyDot,
  uncertaintyLabel,
} from "./findingStyles";
import { buttonStyles, chip } from "./ui";

interface FindingDetailProps {
  finding: Finding;
  /** 1-based number matching the timeline marker. */
  number: number;
  selected: boolean;
  /** True while the video playhead is inside this finding's time range. */
  inView: boolean;
  canUndo: boolean;
  onSelect: () => void;
  onDecide: (status: ReviewStatus) => void;
  onUndo: () => void;
}

export function FindingDetail({
  finding,
  number,
  selected,
  inView,
  canUndo,
  onSelect,
  onDecide,
  onUndo,
}: FindingDetailProps) {
  const { reviewStatus, uncertainty } = finding;
  const headingId = `finding-${finding.eventId}-title`;

  return (
    <article
      id={`finding-${finding.eventId}`}
      aria-labelledby={headingId}
      className={`relative overflow-hidden rounded-[3px] border bg-surface before:absolute before:inset-x-0 before:top-0 before:h-[3px] ${statusEdge[reviewStatus]} ${
        selected ? "border-accent ring-1 ring-accent" : "border-line hover:border-line-strong"
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="flex w-full items-start gap-3 px-4 pb-2 pt-4 text-left"
      >
        <span
          className={`flex size-6 shrink-0 items-center justify-center rounded-[2px] font-mono text-[11px] font-semibold ${markerClass(finding)}`}
          aria-hidden="true"
        >
          {number}
        </span>
        <span className="min-w-0 flex-1">
          <span className="tabular flex flex-wrap items-center gap-x-2 font-mono text-[12px] text-ink-muted">
            {formatTimestamp(finding.timestampSec)}
            {finding.endSec != null && <span>→ {formatTimestamp(finding.endSec)}</span>}
            {inView && (
              <span className="eyebrow inline-flex items-center gap-1 text-accent">
                <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" /> Playing
              </span>
            )}
          </span>
          <span id={headingId} className="mt-1 block text-[16px] font-semibold leading-snug tracking-[-0.01em]">
            {finding.title}
          </span>
          <span className="sr-only">Jump to this moment</span>
        </span>
      </button>

      <div className="space-y-2.5 px-4 pb-4 pl-[52px] text-[14px] leading-relaxed">
        <div className="flex flex-wrap gap-1.5">
          <span className={`${chip} ${statusChip[reviewStatus]}`}>
            <span className={`size-1.5 rounded-full ${statusDot[reviewStatus]}`} aria-hidden="true" />
            {statusLabel[reviewStatus]}
          </span>
          <span className={`${chip} ${uncertaintyChip[uncertainty.level]}`}>
            <span className={`size-1.5 rounded-full ${uncertaintyDot[uncertainty.level]}`} aria-hidden="true" />
            {uncertaintyLabel[uncertainty.level]}
          </span>
        </div>

        <dl className="space-y-2">
          <div>
            <dt className="eyebrow text-ink-faint">Observed</dt>
            <dd className="mt-0.5">{finding.description}</dd>
          </div>
          <div>
            <dt className="eyebrow text-ink-faint">Why review</dt>
            <dd className="mt-0.5 text-ink-muted">{finding.reasonForReview}</dd>
          </div>
          <div>
            <dt className={`eyebrow ${uncertainty.level === "low" ? "text-ink-faint" : "text-amber"}`}>Limits</dt>
            <dd className={`mt-0.5 ${uncertainty.level === "low" ? "text-ink-muted" : "text-amber"}`}>{uncertainty.notes}</dd>
          </div>
        </dl>

        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          {reviewStatus === "needs_review" ? (
            <>
              <button type="button" className={buttonStyles.small} onClick={() => onDecide("confirmed")}>
                Confirm
              </button>
              <button type="button" className={buttonStyles.small} onClick={() => onDecide("dismissed")}>
                Dismiss
              </button>
            </>
          ) : (
            <p className="text-[13px] text-ink-muted">
              {reviewStatus === "confirmed" ? "You confirmed this finding." : "You dismissed this finding."}
            </p>
          )}
          {canUndo && (
            <button type="button" className="eyebrow ml-auto text-accent underline-offset-4 hover:underline" onClick={onUndo}>
              Undo
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
