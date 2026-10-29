// Shared data shapes for reScrub.
// The backend must return JSON in exactly these shapes (see docs/API.md at the repository root).

/** What the reviewer decided about a finding. */
export type ReviewStatus = "needs_review" | "confirmed" | "dismissed";

/** How confident the analysis is that the moment was seen clearly. */
export type UncertaintyLevel = "low" | "medium" | "high";

/** One step in a contact chain, e.g. "Side table" touched at 11.0s. */
export interface EvidenceStep {
  /** Plain-language name of the object or area, e.g. "Right glove". */
  label: string;
  /**
   * "sterile" / "nonsterile" ONLY when the procedure context or a visible label in
   * the scene says so. Sterility can't be judged from appearance, so anything else
   * (including views that are blocked) must be "unknown".
   */
  designation: "sterile" | "nonsterile" | "unknown";
  /** When this contact is visible in the recording, in seconds. */
  timestampSec: number;
  /** Short description of what is visible at that moment. */
  observation: string;
}

/** A moment the analysis thinks a person should look at. */
export interface Finding {
  sessionId: string;
  eventId: string;
  /** Where the reviewer should start watching, in seconds. */
  timestampSec: number;
  /** Optional end of the moment, in seconds. */
  endSec?: number;
  title: string;
  /** Objects or areas involved, e.g. ["Side table", "Right glove", "Forceps"]. */
  objects: string[];
  /** What was observed, written neutrally. */
  description: string;
  /** Why a human should review this moment. */
  reasonForReview: string;
  /** The contact chain, in order, each step with its own timestamp. */
  evidence: EvidenceStep[];
  uncertainty: {
    level: UncertaintyLevel;
    /** Visibility or ambiguity limits, e.g. "hand may be hovering, not touching". */
    notes: string;
  };
  reviewStatus: ReviewStatus;
}

/** Everything the frontend needs to show one reviewed recording. */
export interface AnalysisResult {
  sessionId: string;
  /** "demo" results are sample data and must never be attached to a user's upload. */
  source: "demo" | "backend";
  createdAt: string;
  findings: Finding[];
  /** How many findings the website ignored because they failed validation. */
  discardedFindings?: number;
  /**
   * Backend only: the recording with people, arm/hand points and sterile/nonsterile
   * surfaces drawn on it (H.264 MP4), streamed by the analysis API itself. Only
   * accepted when it points at the configured backend (see lib/validate.ts).
   */
  annotatedVideoUrl?: string;
}

/** What the uploader tells us about the recording. */
export interface SessionDetails {
  name: string;
  /** Optional free text: what is practiced, camera placement, and any protocol notes. */
  procedureContext: string;
  acknowledged: boolean;
}

/** Backend job states reported while a recording is processed. */
export type JobState = "queued" | "analyzing" | "completed" | "failed" | "canceled";

export interface JobStatus {
  sessionId: string;
  state: JobState;
  /** The session name given at upload (empty if none). */
  name?: string;
  /** 0–1 while analyzing. */
  progress?: number;
  /** While queued: how many recordings the server will analyze before this one. */
  queuePosition?: number;
  /** Present when state is "completed". */
  result?: AnalysisResult;
  /** Human-readable reason when state is "failed". */
  error?: string;
}

/** One of the signed-in user's recordings (GET /sessions). */
export interface RecordingSummary {
  sessionId: string;
  name: string;
  state: JobState;
  progress: number;
  createdAt: string;
}

/** One moment highlighted in the final report. Times, titles and statuses come from the findings. */
export interface ReportMoment {
  eventId: string;
  timestampSec: number;
  title: string;
  reviewStatus: ReviewStatus;
  uncertainty: UncertaintyLevel;
  /** Written by Gemini (backend) or by hand (demo). */
  summary: string;
  teachingPoint: string;
}

/** Final review report for a session (POST/GET /sessions/{id}/report; docs/API.md). */
export interface ReviewReport {
  /** "gemini" = written by the backend with Google Gemini; "demo" = sample text for the demonstration. */
  source: "gemini" | "demo";
  generatedAt: string;
  model: string;
  overview: string;
  keyMoments: ReportMoment[];
  coachingPoints: string[];
  limitations: string;
  stats: { findings: number; confirmed: number; needsReview: number; dismissed: number; highUncertainty: number };
  /** True when reviewer decisions changed after the report was written. */
  stale: boolean;
}

/** Every screen state the workspace can be in. */
export type WorkspaceState =
  | "no_video"
  | "ready"
  | "uploading"
  | "queued"
  | "analyzing"
  | "completed"
  | "failed"
  | "canceled";
