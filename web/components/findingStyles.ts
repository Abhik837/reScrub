// Colors and labels for findings, shared by the timeline, list, and chain.
// Color is never the only signal: every state also has a text label.

import type { EvidenceStep, Finding, ReviewStatus, UncertaintyLevel } from "@/lib/types";

export const statusLabel: Record<ReviewStatus, string> = {
  needs_review: "Needs review",
  confirmed: "Confirmed",
  dismissed: "Dismissed",
};

/** Chip text + background for each review status. */
export const statusChip: Record<ReviewStatus, string> = {
  needs_review: "bg-flag-soft text-flag",
  confirmed: "bg-ink text-white",
  dismissed: "bg-surface-sunken text-ink-muted",
};

export const statusDot: Record<ReviewStatus, string> = {
  needs_review: "bg-flag-mark",
  confirmed: "bg-white",
  dismissed: "bg-ink-faint",
};

/** Thin colored edge on top of each finding row (as on altair-health.com cards). */
export const statusEdge: Record<ReviewStatus, string> = {
  needs_review: "before:bg-flag-mark",
  confirmed: "before:bg-ink",
  dismissed: "before:bg-line-strong",
};

export const uncertaintyLabel: Record<UncertaintyLevel, string> = {
  low: "Clear view",
  medium: "Some uncertainty",
  high: "High uncertainty",
};

export const uncertaintyChip: Record<UncertaintyLevel, string> = {
  low: "bg-surface-sunken text-ink-muted",
  medium: "bg-amber-soft text-amber",
  high: "bg-amber-soft text-amber",
};

export const uncertaintyDot: Record<UncertaintyLevel, string> = {
  low: "bg-ok-mark",
  medium: "bg-amber-mark",
  high: "bg-amber-mark",
};

/** Timeline marker color: red for flagged, amber when visibility is poor, navy once confirmed, gray once dismissed. */
export function markerClass(finding: Finding): string {
  if (finding.reviewStatus === "dismissed") return "bg-line-strong text-ink";
  if (finding.reviewStatus === "confirmed") return "bg-ink text-white";
  if (finding.uncertainty.level === "high") return "bg-amber-mark text-ink";
  return "bg-flag-mark text-white";
}

export const designationLabel: Record<EvidenceStep["designation"], string> = {
  sterile: "Sterile",
  nonsterile: "Nonsterile",
  unknown: "Unclear",
};

export const designationText: Record<EvidenceStep["designation"], string> = {
  sterile: "text-ok",
  nonsterile: "text-flag",
  unknown: "text-amber",
};

export const designationDot: Record<EvidenceStep["designation"], string> = {
  sterile: "bg-ok-mark",
  nonsterile: "bg-flag-mark",
  unknown: "bg-amber-mark",
};
