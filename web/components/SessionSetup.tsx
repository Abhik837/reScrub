"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { MAX_CONTEXT_LENGTH, MAX_NAME_LENGTH, isBackendConfigured } from "@/lib/api";
import type { SessionDetails } from "@/lib/types";
import { SetupStep } from "./SetupStep";
import { buttonStyles } from "./ui";

interface SessionSetupProps {
  details: SessionDetails;
  hasFile: boolean;
  /** True while uploading/analyzing. */
  locked: boolean;
  /** The upload area, shown as step 01. */
  recording: ReactNode;
  /** Upload/analysis status panel, shown in step 04 when a job exists. */
  status: ReactNode;
  onChange: (patch: Partial<SessionDetails>) => void;
  onAnalyze: () => void;
}

const fieldClass =
  "w-full rounded-[3px] border border-line-strong bg-surface px-3 py-2.5 text-[15px] text-ink placeholder:text-ink-faint hover:border-ink-faint focus:border-primary disabled:bg-surface-sunken";

/** Lists what's still needed before analysis can start. */
export function missingForAnalysis(details: SessionDetails, hasFile: boolean): string[] {
  const missing: string[] = [];
  if (!hasFile) missing.push("add an MP4 recording");
  if (!details.name.trim()) missing.push("name the session");
  if (!details.acknowledged) missing.push("accept the upload acknowledgment");
  return missing;
}

export function SessionSetup({
  details,
  hasFile,
  locked,
  recording,
  status,
  onChange,
  onAnalyze,
}: SessionSetupProps) {
  const missing = missingForAnalysis(details, hasFile);
  const canAnalyze = isBackendConfigured && missing.length === 0 && !locked;
  const contextDone = details.name.trim() !== "";

  return (
    <form
      aria-label="Set up a review"
      onSubmit={(e) => {
        e.preventDefault();
        if (canAnalyze) onAnalyze();
      }}
    >
      <ol>
        <SetupStep number={1} label="Recording" title="Add the procedure video" done={hasFile}>
          {recording}
        </SetupStep>

        <SetupStep number={2} label="Context" title="Describe the session" done={contextDone}>
          <fieldset disabled={locked} className="grid gap-5">
            <div>
              <label htmlFor="session-name" className="mb-1.5 block text-sm font-medium">
                Session name <span className="font-normal text-ink-faint">· required</span>
              </label>
              <input
                id="session-name"
                className={fieldClass}
                value={details.name}
                onChange={(e) => onChange({ name: e.target.value })}
                placeholder="e.g. Suturing lab, station 3"
                autoComplete="off"
                maxLength={MAX_NAME_LENGTH}
              />
            </div>
            <div>
              <label htmlFor="procedure-context" className="mb-1.5 block text-sm font-medium">
                Procedure context <span className="font-normal text-ink-faint">· optional</span>
              </label>
              <textarea
                id="procedure-context"
                aria-describedby="procedure-context-hint"
                className={`${fieldClass} min-h-24`}
                value={details.procedureContext}
                onChange={(e) => onChange({ procedureContext: e.target.value })}
                placeholder="What is being practiced, how the camera is placed, and any protocol notes."
                maxLength={MAX_CONTEXT_LENGTH}
              />
              <p id="procedure-context-hint" className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">
                Context can help the analysis spot possible protocol breaks. It can’t tell whether
                something is sterile by looking at it, so unclear moments stay marked as uncertain.
                Don’t include names or other identifying details.{" "}
                <span className="tabular font-mono text-[12px] text-ink-faint">
                  {details.procedureContext.length}/{MAX_CONTEXT_LENGTH}
                </span>
              </p>
            </div>
          </fieldset>
        </SetupStep>

        <SetupStep number={3} label="Permission" title="Confirm you may use this footage" done={details.acknowledged}>
          <fieldset disabled={locked}>
            <div className="flex gap-3 rounded-r-[3px] border border-l-2 border-line border-l-primary bg-surface px-4 py-3.5">
              <input
                id="acknowledgment"
                type="checkbox"
                className="mt-1 size-4 shrink-0 accent-primary"
                checked={details.acknowledged}
                onChange={(e) => onChange({ acknowledged: e.target.checked })}
              />
              <label htmlFor="acknowledgment" className="text-[15px] leading-relaxed">
                I have permission to use this recording. It is simulated or appropriately
                de-identified footage suitable for training, and I’ve read the{" "}
                <Link href="/terms" className="text-accent underline underline-offset-2">
                  Terms
                </Link>{" "}
                and{" "}
                <Link href="/privacy" className="text-accent underline underline-offset-2">
                  Privacy
                </Link>{" "}
                notes.
              </label>
            </div>
          </fieldset>
        </SetupStep>

        <SetupStep number={4} label="Analyze" title="Find moments to review" done={false} last>
          {status && <div className="mb-4">{status}</div>}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              type="submit"
              className={`${buttonStyles.primary} min-h-11 shrink-0 whitespace-nowrap px-6`}
              disabled={!canAnalyze}
              aria-describedby="analyze-help"
            >
              Analyze recording
            </button>
            <p id="analyze-help" className="text-sm text-ink-muted" aria-live="polite">
              {!isBackendConfigured ? (
                <>
                  <span className="font-medium text-amber">Analysis isn’t connected on this site.</span>{" "}
                  Your video stays on this device. Open the demonstration to see a review.
                </>
              ) : missing.length > 0 ? (
                <>To start, {missing.join(", ")}.</>
              ) : (
                <>The recording will be uploaded to the reScrub analysis server.</>
              )}
            </p>
          </div>
        </SetupStep>
      </ol>
    </form>
  );
}
