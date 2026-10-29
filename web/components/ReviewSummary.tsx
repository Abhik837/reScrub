import { formatDuration } from "@/lib/format";
import type { AnalysisResult, Finding } from "@/lib/types";
import { buttonStyles } from "./ui";

interface ReviewSummaryProps {
  sessionName: string;
  fileName: string;
  durationSec: number;
  source: AnalysisResult["source"];
  findings: Finding[];
  /** Message about where reviewer decisions are stored. */
  storageNote: string;
  /** Download the findings and decisions as JSON. */
  onExport: () => void;
  /** Open the print dialog for the review document ("Save as PDF"). */
  onExportPdf: () => void;
  /** Present only for a recording stored on the server (not the demo). */
  onDelete?: () => void;
  /** The labeled video's address on this site, when the server made one (not the demo). */
  labeledVideoUrl?: string;
}

export function ReviewSummary({
  sessionName,
  fileName,
  durationSec,
  source,
  findings,
  storageNote,
  onExport,
  onExportPdf,
  onDelete,
  labeledVideoUrl,
}: ReviewSummaryProps) {
  const count = (s: Finding["reviewStatus"]) => findings.filter((f) => f.reviewStatus === s).length;
  const stats = [
    { label: "Findings", value: findings.length },
    { label: "To review", value: count("needs_review") },
    { label: "Confirmed", value: count("confirmed") },
    { label: "Dismissed", value: count("dismissed") },
  ];

  return (
    <section aria-labelledby="summary-heading" className="flex flex-col gap-5 lg:flex-row lg:items-end lg:gap-10">
      <div className="min-w-0 lg:flex-1">
        <p className="eyebrow text-ink-faint">{source === "demo" ? "Demonstration session" : "Session"}</p>
        <h1
          id="summary-heading"
          className="font-display mt-2 text-[32px] leading-[1.1] tracking-[-0.015em] sm:text-[40px]"
        >
          {sessionName}
        </h1>
        <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-sm text-ink-muted">
          <span className="font-mono text-[13px]">{fileName}</span>
          <span aria-hidden="true">·</span>
          <span className="tabular font-mono text-[13px]">{formatDuration(durationSec)}</span>
          <span aria-hidden="true">·</span>
          <span>{storageNote}</span>
        </p>
      </div>

      <dl className="grid grid-cols-4 border-y border-line lg:border-y-0">
        {stats.map((s, i) => (
          <div key={s.label} className={`px-3 py-3 lg:py-0 ${i > 0 ? "border-l border-line" : "lg:pl-0"} sm:px-5`}>
            <dt className="eyebrow text-ink-faint">{s.label}</dt>
            <dd className="font-display tabular mt-1 text-[34px] leading-none">{s.value}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-col gap-2 self-start lg:self-end">
        <button type="button" className={`${buttonStyles.primary} min-h-11 px-6`} onClick={onExportPdf}>
          Export review PDF
        </button>
        <button type="button" className={`${buttonStyles.secondary} min-h-11 px-6`} onClick={onExport}>
          Export incident JSON
        </button>
        {labeledVideoUrl && (
          // Same-origin link: the sign-in cookie authorizes it, and ?download=1 makes the server send it as a file.
          <a href={`${labeledVideoUrl}?download=1`} download className={`${buttonStyles.secondary} min-h-11 px-6`}>
            Download labeled video
          </a>
        )}
        {onDelete && (
          <button type="button" className={`${buttonStyles.secondary} min-h-11 px-6`} onClick={onDelete}>
            Delete recording
          </button>
        )}
      </div>
    </section>
  );
}
