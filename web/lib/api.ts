// The one place the website talks to the analysis API (docs/API.md lists every endpoint).
// Sign-in calls are in lib/auth.ts.
//
// No secrets belong here: this code runs in the browser. The backend URL is
// public; the database password and storage keys stay on the server.

import type { Finding, JobStatus, RecordingSummary, ReviewReport, ReviewStatus, SessionDetails } from "./types";
import {
  LIMITS,
  ValidationError,
  cleanText,
  isSafeId,
  parseJobStatus,
  parseRecordingList,
  parseReport,
  parseSessionId,
} from "./validate";

/** Longest session name / context we send. The backend must enforce its own limits too. */
export const MAX_NAME_LENGTH = 120;
export const MAX_CONTEXT_LENGTH = 2000;

const REQUEST_TIMEOUT_MS = 15_000;
/** Generous, so a 500 MB file on a slow connection can still finish. */
const UPLOAD_TIMEOUT_MS = 60 * 60 * 1000;

/**
 * The backend address from NEXT_PUBLIC_API_BASE_URL, normally "/api": the API
 * is served on the website's own origin, so the sign-in cookie never crosses sites and no
 * CORS is involved. An absolute URL must be HTTPS (plain http:// only for localhost).
 */
function readBaseUrl(raw: string | undefined): string {
  if (!raw) return "";
  if (/^\/[A-Za-z0-9/_-]*$/.test(raw)) return raw.replace(/\/$/, "");
  try {
    const url = new URL(raw);
    const local = url.hostname === "localhost" || url.hostname === "127.0.0.1";
    if (url.protocol === "https:" || (url.protocol === "http:" && local)) return url.origin + url.pathname.replace(/\/$/, "");
  } catch {
    // fall through
  }
  return "";
}

const API_BASE_URL = readBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL);

/** True when a valid (HTTPS, or localhost) backend address has been configured. */
export const isBackendConfigured = API_BASE_URL.length > 0;

/** The API base for building URLs ("/api" or an absolute HTTPS URL). */
export const apiBaseUrl = API_BASE_URL;

/** Where to send someone whose sign-in is missing or expired, returning them here afterwards. */
function redirectToSignIn(): void {
  if (typeof window === "undefined") return;
  const next = window.location.pathname + window.location.search;
  // Full page load on purpose: the server must see the changed sign-in cookie.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

export class ApiError extends Error {
  constructor(
    message: string,
    /** Whether trying again might work (network blip vs. rejected file). */
    public retryable: boolean,
    /** HTTP status when the server answered with an error. */
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function notConfigured(): never {
  throw new ApiError(
    "Analysis is not connected. Set NEXT_PUBLIC_API_BASE_URL to \"/api\" to enable it.",
    false,
  );
}

/** Turn a server error body into a short plain-text message (never HTML). */
function serverMessage(body: unknown, status: number, fallback: string): string {
  const raw = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  return cleanText(raw.error, LIMITS.error) ?? cleanText(raw.detail, LIMITS.error) ?? `${fallback} (HTTP ${status}).`;
}

function asApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (err instanceof ValidationError) return new ApiError(err.message, true);
  return new ApiError("Something unexpected went wrong. Please try again.", true);
}

/**
 * Upload the recording and session details. Resolves with the new session ID.
 * `onProgress` receives real upload progress from the browser (0–1).
 */
export function uploadRecording(
  file: File,
  details: SessionDetails,
  onProgress: (fraction: number) => void,
  signal: AbortSignal,
): Promise<{ sessionId: string }> {
  if (!isBackendConfigured) notConfigured();

  const form = new FormData();
  // The original filename is sent as-is for display only. The backend must
  // never use it to build a storage path (see docs/SECURITY.md at the repository root).
  form.append("video", file);
  form.append("name", details.name.trim().slice(0, MAX_NAME_LENGTH));
  form.append("procedureContext", details.procedureContext.trim().slice(0, MAX_CONTEXT_LENGTH));
  form.append("acknowledged", String(details.acknowledged));

  // XMLHttpRequest (not fetch) because it reports real upload progress.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/sessions`);
    xhr.withCredentials = true; // send the sign-in cookie
    xhr.responseType = "json";
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve({ sessionId: parseSessionId(xhr.response) });
        } catch (err) {
          reject(asApiError(err));
        }
      } else {
        if (xhr.status === 401) redirectToSignIn();
        reject(new ApiError(serverMessage(xhr.response, xhr.status, "The server rejected the upload"), xhr.status >= 500));
      }
    };
    xhr.onerror = () => reject(new ApiError("Could not reach the analysis server. Check your connection.", true));
    xhr.ontimeout = () => reject(new ApiError("The upload took too long and was stopped.", true));
    xhr.onabort = () => reject(new DOMException("Upload canceled", "AbortError"));
    signal.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

export async function request(path: string, init: RequestInit = {}, timeoutMs = REQUEST_TIMEOUT_MS): Promise<unknown> {
  if (!isBackendConfigured) notConfigured();
  // Every request gets a timeout, plus the caller's cancel signal if given.
  const timeout = AbortSignal.timeout(timeoutMs);
  const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...init, signal, credentials: "include" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError" && init.signal?.aborted) throw err;
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new ApiError("The analysis server took too long to respond.", true);
    }
    throw new ApiError("Could not reach the analysis server. Check your connection.", true);
  }
  const body = await res.json().catch(() => null);
  if (res.status === 401 && !path.startsWith("/auth/")) redirectToSignIn();
  if (!res.ok) throw new ApiError(serverMessage(body, res.status, "Request failed"), res.status >= 500, res.status);
  return body;
}

function sessionPath(sessionId: string, rest = ""): string {
  if (!isSafeId(sessionId)) throw new ApiError("Invalid session ID.", false);
  return `/sessions/${encodeURIComponent(sessionId)}${rest}`;
}

/** Ask the backend how the analysis job is going. The response is validated before use. */
export async function getJobStatus(sessionId: string, signal?: AbortSignal): Promise<JobStatus> {
  const body = await request(sessionPath(sessionId), { signal });
  try {
    return parseJobStatus(body, sessionId, API_BASE_URL);
  } catch (err) {
    throw asApiError(err);
  }
}

/** The signed-in user's recent recordings, newest first. Validated before use. */
export async function listRecordings(signal?: AbortSignal): Promise<RecordingSummary[]> {
  const body = await request("/sessions", { signal });
  try {
    return parseRecordingList(body);
  } catch (err) {
    throw asApiError(err);
  }
}

/** Ask the backend to stop processing. */
export async function cancelJob(sessionId: string): Promise<void> {
  await request(sessionPath(sessionId, "/cancel"), { method: "POST" });
}

/** Delete the recording, labeled video, tracking data and findings on the server. */
export async function deleteRecording(sessionId: string): Promise<void> {
  await request(sessionPath(sessionId), { method: "DELETE" });
}

/** Writing a report waits on Gemini; allow longer than ordinary requests. */
const REPORT_TIMEOUT_MS = 90_000;

/** The saved final report, or null if none has been written yet. Validated before use. */
export async function getReport(sessionId: string, findings: Finding[]): Promise<ReviewReport | null> {
  try {
    return parseReport(await request(sessionPath(sessionId, "/report")), sessionId, findings);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw asApiError(err);
  }
}

/**
 * Ask the backend to write a final report with Google Gemini from the findings and reviewer
 * decisions (the video is never sent). Validated before use.
 */
export async function writeReport(sessionId: string, findings: Finding[]): Promise<ReviewReport> {
  const body = await request(sessionPath(sessionId, "/report"), { method: "POST" }, REPORT_TIMEOUT_MS);
  try {
    return parseReport(body, sessionId, findings);
  } catch (err) {
    throw asApiError(err);
  }
}

/** Save a reviewer's decision on one finding. */
export async function saveReviewDecision(sessionId: string, eventId: string, reviewStatus: ReviewStatus): Promise<void> {
  if (!isSafeId(eventId)) throw new ApiError("Invalid finding ID.", false);
  await request(sessionPath(sessionId, `/findings/${encodeURIComponent(eventId)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewStatus }),
  });
}
