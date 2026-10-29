import type { ReactNode } from "react";

interface SetupStepProps {
  number: number;
  label: string;
  title: string;
  done: boolean;
  last?: boolean;
  children: ReactNode;
}

/**
 * One numbered step in the setup flow: a number square and a vertical line on
 * the left, content on the right (the stepper pattern from altair-health.com).
 */
export function SetupStep({ number, label, title, done, last = false, children }: SetupStepProps) {
  const id = `step-${number}-title`;
  return (
    <li aria-labelledby={id} className="grid grid-cols-[36px_minmax(0,1fr)] gap-x-4 sm:grid-cols-[44px_minmax(0,1fr)] sm:gap-x-6">
      <div className="flex flex-col items-center">
        <span
          className={`eyebrow flex size-9 shrink-0 items-center justify-center rounded-[2px] border-[1.5px] tracking-normal sm:size-11 ${
            done ? "border-primary bg-primary text-white" : "border-line-strong bg-surface text-ink-muted"
          }`}
        >
          {done ? (
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <path d="M2.5 7.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" />
            </svg>
          ) : (
            String(number).padStart(2, "0")
          )}
          <span className="sr-only">{done ? `Step ${number} complete` : `Step ${number}`}</span>
        </span>
        {!last && <span aria-hidden="true" className="mt-2 w-px flex-1 bg-line-strong" />}
      </div>
      <div className={last ? "pb-2" : "pb-10"}>
        <p className="eyebrow pt-0.5 text-ink-faint sm:pt-1">{label}</p>
        <h2 id={id} className="mt-1 text-lg font-semibold tracking-[-0.01em]">
          {title}
        </h2>
        <div className="mt-4">{children}</div>
      </div>
    </li>
  );
}
