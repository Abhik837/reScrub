"use client";

import { Fragment } from "react";
import { formatTimestamp } from "@/lib/format";
import type { Finding } from "@/lib/types";
import { designationDot, designationLabel, designationText } from "./findingStyles";

interface ContactChainProps {
  finding: Finding | null;
  number: number;
  currentTime: number;
  onSeek: (seconds: number) => void;
}

/**
 * Shows the sequence of contacts behind a finding, e.g.
 * Side table → Right glove → Forceps, each with the moment it's visible.
 * It does not draw boxes or claim tracked positions: the analysis only
 * reports what happened and when.
 */
export function ContactChain({ finding, number, currentTime, onSeek }: ContactChainProps) {
  const header = (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 id="chain-heading" className="eyebrow text-ink">
        Evidence{finding && <span className="text-ink-faint"> · Finding {number}</span>}
      </h2>
      {finding && <p className="text-[13px] text-ink-muted">Select a step to watch that moment</p>}
    </div>
  );

  if (!finding) {
    return (
      <section aria-labelledby="chain-heading" className="rounded-[3px] border border-line bg-surface px-4 py-3.5">
        {header}
        <p className="mt-2 text-sm text-ink-muted">Select a finding to see its contact chain.</p>
      </section>
    );
  }

  const steps = finding.evidence;
  const windowEnd = finding.endSec ?? (steps.at(-1)?.timestampSec ?? finding.timestampSec) + 2;
  const inWindow = currentTime >= finding.timestampSec - 0.5 && currentTime <= windowEnd;
  // The step the playhead has most recently passed is "current".
  let activeIndex = -1;
  if (inWindow) {
    steps.forEach((s, i) => {
      if (currentTime + 0.05 >= s.timestampSec) activeIndex = i;
    });
  }

  return (
    <section aria-labelledby="chain-heading" className="rounded-[3px] border border-line bg-surface px-4 py-3.5">
      {header}
      <p className="font-display mt-2 text-[22px] leading-snug tracking-[-0.01em]">{finding.title}</p>

      {steps.length === 0 ? (
        <p className="mt-3 text-sm text-ink-muted">The analysis did not report a contact chain for this finding.</p>
      ) : (
        <ol className="mt-4 flex flex-col gap-2 md:flex-row md:items-stretch md:gap-0">
          {steps.map((step, i) => {
            const active = i === activeIndex;
            return (
              <Fragment key={`${step.label}-${step.timestampSec}`}>
                {i > 0 && (
                  <li aria-hidden="true" className="flex items-center justify-center text-ink-faint md:w-8">
                    <span className="h-4 w-px bg-line-strong md:h-px md:w-full" />
                  </li>
                )}
                <li className="md:min-w-0 md:flex-1">
                  <button
                    type="button"
                    onClick={() => onSeek(step.timestampSec)}
                    aria-current={active ? "step" : undefined}
                    className={`h-full w-full rounded-[3px] border px-3.5 py-3 text-left transition-colors ${
                      active ? "border-accent bg-accent-soft" : "border-line bg-canvas hover:border-ink"
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className={`eyebrow flex items-center gap-1.5 ${designationText[step.designation]}`}>
                        <span className={`size-1.5 rounded-full ${designationDot[step.designation]}`} aria-hidden="true" />
                        {designationLabel[step.designation]}
                      </span>
                      <span className="tabular font-mono text-xs text-ink-muted">{formatTimestamp(step.timestampSec)}</span>
                    </span>
                    <span className="mt-1.5 block text-[15px] font-semibold">{step.label}</span>
                    <span className="mt-0.5 block text-[13px] leading-snug text-ink-muted">{step.observation}</span>
                  </button>
                </li>
              </Fragment>
            );
          })}
        </ol>
      )}

      <p className="mt-4 border-t border-line pt-3 text-[13px] text-ink-muted">
        This chain is the analysis’s description of what happened and when, from tracked hand and
        surface positions seen by one camera. Watch each moment before you decide.
      </p>
    </section>
  );
}
