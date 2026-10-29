// Strict checks for everything the backend sends.
// The backend must validate too; this is a second line of defense so a bad or
// malicious response can't break the page or spoof the interface.
//
// All text is rendered by React as plain text (never as HTML), so markup in a
// response shows up literally instead of running.

import type {
  AnalysisResult,
  EvidenceStep,
  Finding,
  JobState,
  RecordingSummary,
  JobStatus,
  ReportMoment,
  ReviewReport,
  ReviewStatus,
  UncertaintyLevel,
} from "./types";

export const LIMITS = {
  maxFindings: 200,
  maxEvidenceSteps: 12,
  maxObjects: 20,
  /** 6 hours, far longer than any practice recording. */
  maxTimestampSec: 6 * 60 * 60,
  title: 140,
  label: 80,
  text: 1000,
  error: 500,
} as const;

/** IDs are used in URLs and HTML ids, so keep them to a safe character set. */
const ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

// Control characters and bidirectional-override characters can be used to
// disguise text (e.g. make a filename or label read backwards).
const UNSAFE_CHARS = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F‪-‮⁦-⁩]/g;

export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Plain text only: strip unsafe characters, trim, and cap the length. */
export function cleanText(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.replace(UNSAFE_CHARS, "").trim();
  if (!cleaned) return null;
  return cleaned.length > max ? `${cleaned.slice(0, max - 1)}…` : cleaned;
}

export function isSafeId(value: unknown): value is string {
  return typeof value === "string" && ID_PATTERN.test(value);
}

function seconds(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= LIMITS.maxTimestampSec
    ? value
    : null;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T | null {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

const JOB_STATES = ["queued", "analyzing", "completed", "failed", "canceled"] as const satisfies readonly JobState[];
const REVIEW_STATUSES = ["needs_review", "confirmed", "dismissed"] as const satisfies readonly ReviewStatus[];
const UNCERTAINTY = ["low", "medium", "high"] as const satisfies readonly UncertaintyLevel[];
const DESIGNATIONS = ["sterile", "nonsterile", "unknown"] as const satisfies readonly EvidenceStep["designation"][];

function parseStep(raw: unknown): EvidenceStep | null {
  if (!isObject(raw)) return null;
  const label = cleanText(raw.label, LIMITS.label);
  const timestampSec = seconds(raw.timestampSec);
  if (!label || timestampSec === null) return null;
  return {
    label,
    // Anything the backend can't justify is shown as "Unclear", never guessed.
    designation: oneOf(raw.designation, DESIGNATIONS) ?? "unknown",
    timestampSec,
    observation: cleanText(raw.observation, LIMITS.text) ?? "",
  };
}

function parseFinding(raw: unknown, sessionId: string): Finding | null {
  if (!isObject(raw)) return null;
  const eventId = raw.eventId;
  const timestampSec = seconds(raw.timestampSec);
  const title = cleanText(raw.title, LIMITS.title);
  const description = cleanText(raw.description, LIMITS.text);
  if (!isSafeId(eventId) || timestampSec === null || !title || !description) return null;

  const end = raw.endSec == null ? undefined : seconds(raw.endSec);
  const uncertainty = isObject(raw.uncertainty) ? raw.uncertainty : {};

  return {
    sessionId,
    eventId,
    timestampSec,
    endSec: end != null && end >= timestampSec ? end : undefined,
    title,
    objects: (Array.isArray(raw.objects) ? raw.objects : [])
      .slice(0, LIMITS.maxObjects)
      .map((o) => cleanText(o, LIMITS.label))
      .filter((o): o is string => o !== null),
    description,
    reasonForReview: cleanText(raw.reasonForReview, LIMITS.text) ?? "No reason was given. Watch this moment before deciding.",
    evidence: (Array.isArray(raw.evidence) ? raw.evidence : [])
      .slice(0, LIMITS.maxEvidenceSteps)
      .map(parseStep)
      .filter((s): s is EvidenceStep => s !== null)
      .sort((a, b) => a.timestampSec - b.timestampSec),
    uncertainty: {
      // If the model doesn't say how sure it is, assume it isn't.
      level: oneOf(uncertainty.level, UNCERTAINTY) ?? "high",
      notes: cleanText(uncertainty.notes, LIMITS.text) ?? "The analysis did not describe its limits for this moment.",
    },
    reviewStatus: oneOf(raw.reviewStatus, REVIEW_STATUSES) ?? "needs_review",
  };
}

/**
 * The labeled video must come from the analysis API itself and from exactly this session's
 * path (e.g. "/api/sessions/<id>/annotated.mp4"), never from an arbitrary or storage URL.
 */
export function parseAnnotatedVideoUrl(value: unknown, sessionId: string, apiBase: string): string | undefined {
  if (typeof value !== "string" || !apiBase || value.length > 2048) return undefined;
  try {
    // apiBase may be relative ("/api"): resolve it against this page's origin.
    const here = typeof window === "undefined" ? "https://invalid.local" : window.location.origin;
    const url = new URL(value, here);
    const api = new URL(apiBase, here);
    const expectedPath = `${api.pathname.replace(/\/$/, "")}/sessions/${encodeURIComponent(sessionId)}/annotated.mp4`;
    if (url.origin !== api.origin || url.pathname !== expectedPath || url.search || url.hash) return undefined;
    return url.toString();
  } catch {
    return undefined;
  }
}

function parseResult(raw: unknown, sessionId: string, apiBase: string): AnalysisResult {
  if (!isObject(raw)) throw new ValidationError("The server sent results in an unexpected format.");
  // "demo" is reserved for built-in sample data and must never come from the server.
  if (raw.source !== "backend") throw new ValidationError("The server sent results marked with an unexpected source.");
  if (raw.sessionId !== sessionId) throw new ValidationError("The server sent results for a different session.");
  if (!Array.isArray(raw.findings)) throw new ValidationError("The server sent results without a findings list.");

  const candidates = raw.findings.slice(0, LIMITS.maxFindings);
  const findings: Finding[] = [];
  const seen = new Set<string>();
  for (const item of candidates) {
    const finding = parseFinding(item, sessionId);
    if (finding && !seen.has(finding.eventId)) {
      seen.add(finding.eventId);
      findings.push(finding);
    }
  }

  return {
    sessionId,
    source: "backend",
    createdAt: typeof raw.createdAt === "string" ? raw.createdAt.slice(0, 40) : "",
    findings,
    discardedFindings: raw.findings.length - findings.length,
    annotatedVideoUrl: parseAnnotatedVideoUrl(raw.annotatedVideoUrl, sessionId, apiBase),
  };
}

/** Validate a GET /sessions/{id} response. Throws ValidationError if unusable. */
export function parseJobStatus(raw: unknown, expectedSessionId: string, apiBase = ""): JobStatus {
  if (!isObject(raw)) throw new ValidationError("The server sent a status in an unexpected format.");
  const state = oneOf(raw.state, JOB_STATES);
  if (!state) throw new ValidationError("The server sent an unknown job state.");
  if (raw.sessionId !== undefined && raw.sessionId !== expectedSessionId) {
    throw new ValidationError("The server sent a status for a different session.");
  }
  return {
    sessionId: expectedSessionId,
    state,
    name: cleanText(raw.name, LIMITS.title) ?? undefined,
    progress: fraction(raw.progress),
    queuePosition: typeof raw.queuePosition === "number" ? count(raw.queuePosition) : undefined,
    error: cleanText(raw.error, LIMITS.error) ?? undefined,
    result:
      state === "completed" && raw.result !== undefined ? parseResult(raw.result, expectedSessionId, apiBase) : undefined,
  };
}

function fraction(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : undefined;
}

/** Validate the recordings list from GET /sessions; entries that don't check out are skipped. */
export function parseRecordingList(raw: unknown): RecordingSummary[] {
  if (!isObject(raw) || !Array.isArray(raw.sessions)) {
    throw new ValidationError("The server sent the recordings list in an unexpected format.");
  }
  const out: RecordingSummary[] = [];
  for (const item of raw.sessions.slice(0, 50)) {
    if (!isObject(item) || !isSafeId(item.sessionId)) continue;
    const state = oneOf(item.state, JOB_STATES);
    if (!state) continue;
    out.push({
      sessionId: item.sessionId,
      name: cleanText(item.name, LIMITS.title) ?? "Untitled session",
      state,
      progress: fraction(item.progress) ?? 0,
      createdAt: typeof item.createdAt === "string" ? item.createdAt.slice(0, 40) : "",
    });
  }
  return out;
}

const REPORT_LIMITS = { overview: 1200, summary: 500, teaching: 400, point: 300, limitations: 800, moments: 10, points: 5 };

function count(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 100_000 ? value : 0;
}

/**
 * Validate a final report from GET/POST /sessions/{id}/report. Report text was written by an AI
 * model, so it is held to the same rules as findings: plain text only, capped lengths, and every
 * moment must point at a finding this page actually has (its time and title are taken from that
 * finding, not from the report).
 */
export function parseReport(raw: unknown, sessionId: string, findings: Finding[]): ReviewReport {
  if (!isObject(raw)) throw new ValidationError("The server sent a report in an unexpected format.");
  if (raw.sessionId !== sessionId) throw new ValidationError("The server sent a report for a different session.");
  const overview = cleanText(raw.overview, REPORT_LIMITS.overview);
  if (!overview) throw new ValidationError("The server sent an empty report.");

  const byId = new Map(findings.map((f) => [f.eventId, f]));
  const keyMoments: ReportMoment[] = [];
  for (const m of Array.isArray(raw.keyMoments) ? raw.keyMoments.slice(0, REPORT_LIMITS.moments) : []) {
    if (!isObject(m) || !isSafeId(m.eventId)) continue;
    const finding = byId.get(m.eventId);
    const summary = cleanText(m.summary, REPORT_LIMITS.summary);
    if (!finding || !summary || keyMoments.some((k) => k.eventId === finding.eventId)) continue;
    keyMoments.push({
      eventId: finding.eventId,
      timestampSec: finding.timestampSec,
      title: finding.title,
      reviewStatus: finding.reviewStatus, // the reviewer's current decision on this page
      uncertainty: finding.uncertainty.level,
      summary,
      teachingPoint: cleanText(m.teachingPoint, REPORT_LIMITS.teaching) ?? "",
    });
  }

  const stats = isObject(raw.stats) ? raw.stats : {};
  return {
    source: "gemini",
    generatedAt: typeof raw.generatedAt === "string" ? raw.generatedAt.slice(0, 40) : "",
    model: cleanText(raw.model, 80) ?? "Gemini",
    overview,
    keyMoments,
    coachingPoints: (Array.isArray(raw.coachingPoints) ? raw.coachingPoints : [])
      .map((p) => cleanText(p, REPORT_LIMITS.point))
      .filter((p): p is string => p !== null)
      .slice(0, REPORT_LIMITS.points),
    limitations: cleanText(raw.limitations, REPORT_LIMITS.limitations) ?? "",
    stats: {
      findings: count(stats.findings),
      confirmed: count(stats.confirmed),
      needsReview: count(stats.needsReview),
      dismissed: count(stats.dismissed),
      highUncertainty: count(stats.highUncertainty),
    },
    stale: raw.stale === true,
  };
}

/** Validate a POST /sessions response. */
export function parseSessionId(raw: unknown): string {
  if (isObject(raw) && isSafeId(raw.sessionId)) return raw.sessionId;
  throw new ValidationError("The server sent a session ID in an unexpected format.");
}
