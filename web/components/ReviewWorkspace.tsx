"use client";

// The whole reScrub workspace: setup → upload/analysis → review.
// All page state lives here; the child components just display it.

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  cancelJob,
  getJobStatus,
  isBackendConfigured,
  deleteRecording,
  getReport,
  saveReviewDecision,
  uploadRecording,
  writeReport,
} from "@/lib/api";
import { DEMO_DETAILS, DEMO_RESULT, DEMO_VIDEO_SRC, SAMPLE_DETAILS, SAMPLE_VIDEO_SRC, demoReport } from "@/lib/demo";
import { displayFileName } from "@/lib/format";
import type {
  AnalysisResult,
  Finding,
  ReviewReport,
  ReviewStatus,
  SessionDetails,
  WorkspaceState,
} from "@/lib/types";
import { PrintableReview } from "./PrintableReview";
import { ReportPanel, type ReportStatus } from "./ReportPanel";
import { AnalysisStatus } from "./AnalysisStatus";
import type { Account } from "@/lib/auth";
import { AppHeader } from "./AppHeader";
import { ContactChain } from "./ContactChain";
import { EventTimeline } from "./EventTimeline";
import { FindingsPanel } from "./FindingsPanel";
import { RecentRecordings } from "./RecentRecordings";
import { ReviewSummary } from "./ReviewSummary";
import { SessionSetup } from "./SessionSetup";
import { SiteFooter } from "./SiteFooter";
import { VideoPlayer } from "./VideoPlayer";
import { VideoUpload } from "./VideoUpload";
import { buttonStyles } from "./ui";

const EMPTY_DETAILS: SessionDetails = {
  name: "",
  procedureContext: "",
  acknowledged: false,
};

const DEMO_FINDINGS_SORTED = [...DEMO_RESULT.findings].sort((a, b) => a.timestampSec - b.timestampSec);

const POLL_INTERVAL_MS = 3000;
/** Give up polling after this many network errors in a row. */
const MAX_POLL_ERRORS = 3;

type SyncState = "idle" | "saving" | "saved" | "error";

function toErrorInfo(err: unknown) {
  if (err instanceof ApiError) return { message: err.message, retryable: err.retryable };
  return { message: "Something unexpected went wrong. Please try again.", retryable: true };
}

function isAbort(err: unknown) {
  return err instanceof DOMException && err.name === "AbortError";
}

interface ReviewWorkspaceProps {
  /** Open straight into the demonstration (used by /review?demo=1). */
  startInDemo?: boolean;
  /** The signed-in account, verified on the server (null when unknown). */
  account?: Account | null;
  /** Reopen this recording (from /review?session=<id>), e.g. after a page refresh. */
  resumeSessionId?: string | null;
}

export function ReviewWorkspace({ startInDemo = false, account = null, resumeSessionId = null }: ReviewWorkspaceProps) {
  // --- Setup ---
  // A reopened recording starts as "queued" until the first status check says otherwise.
  const [state, setState] = useState<WorkspaceState>(resumeSessionId ? "queued" : "no_video");
  const [file, setFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [previewDuration, setPreviewDuration] = useState<number | null>(null);
  const [details, setDetails] = useState<SessionDetails>(EMPTY_DETAILS);

  // --- Analysis job ---
  const [sessionId, setSessionId] = useState<string | null>(resumeSessionId);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [analysisProgress, setAnalysisProgress] = useState<number | null>(null);
  const [queuePosition, setQueuePosition] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<{ message: string; retryable: boolean } | null>(null);
  const [cancelNote, setCancelNote] = useState<string | null>(null);

  // --- Review ---
  const [demo, setDemo] = useState(startInDemo);
  const [result, setResult] = useState<AnalysisResult | null>(startInDemo ? DEMO_RESULT : null);
  const [findings, setFindings] = useState<Finding[]>(startInDemo ? DEMO_FINDINGS_SORTED : []);
  const [previous, setPrevious] = useState<Record<string, ReviewStatus>>({});
  const [selectedId, setSelectedId] = useState<string | null>(
    startInDemo ? (DEMO_FINDINGS_SORTED[0]?.eventId ?? null) : null,
  );
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [syncState, setSyncState] = useState<SyncState>("idle");

  // --- Final report ---
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [reportStatus, setReportStatus] = useState<ReportStatus>("idle");
  const [reportError, setReportError] = useState<string | null>(null);
  /** Each finding's decision when the report was written, to notice later changes. */
  const [reportSnapshot, setReportSnapshot] = useState<Record<string, ReviewStatus>>({});

  const videoRef = useRef<HTMLVideoElement>(null);
  const uploadAbort = useRef<AbortController | null>(null);
  const urlRef = useRef<string | null>(null);

  // Free the local video URL when the page closes.
  useEffect(() => () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
  }, []);

  // ---------- File handling ----------

  function setLocalVideo(next: File | null) {
    // Always release the previous URL so replaced videos don't stay in memory.
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = next ? URL.createObjectURL(next) : null;
    setVideoUrl(urlRef.current);
    setFile(next);
    setPreviewDuration(null);
    setState(next ? "ready" : "no_video");
    setError(null);
  }

  // ---------- Analysis ----------

  const openResult = useCallback((next: AnalysisResult) => {
    const sorted = [...next.findings].sort((a, b) => a.timestampSec - b.timestampSec);
    setResult(next);
    setFindings(sorted);
    setPrevious({});
    setSelectedId(sorted[0]?.eventId ?? null);
    setCurrentTime(0);
    setSyncState("idle");
    window.scrollTo({ top: 0 });
  }, []);

  async function startAnalysis(video: File | null = file, sessionDetails: SessionDetails = details) {
    if (!video) return;
    const controller = new AbortController();
    uploadAbort.current = controller;
    setState("uploading");
    setUploadProgress(0);
    setError(null);
    setCancelNote(null);
    try {
      const { sessionId: id } = await uploadRecording(video, sessionDetails, setUploadProgress, controller.signal);
      setSessionId(id);
      setAnalysisProgress(null);
      setQueuePosition(null);
      setState("queued");
      // Keep the recording in the address so a refresh reopens it instead of losing it.
      window.history.replaceState(null, "", `/review?session=${encodeURIComponent(id)}`);
    } catch (err) {
      if (isAbort(err)) {
        setState("canceled");
      } else {
        setError(toErrorInfo(err));
        setState("failed");
      }
    } finally {
      uploadAbort.current = null;
      setUploadProgress(null);
    }
  }

  // Ask the backend for progress every few seconds while a job is running.
  useEffect(() => {
    if (!sessionId || (state !== "queued" && state !== "analyzing")) return;
    const controller = new AbortController();
    let errorsInARow = 0;

    const poll = async () => {
      try {
        const status = await getJobStatus(sessionId, controller.signal);
        errorsInARow = 0;
        setAnalysisProgress(status.progress ?? null);
        setQueuePosition(status.queuePosition ?? null);
        if (status.name) setDetails((d) => (d.name ? d : { ...d, name: status.name ?? "" }));
        if (status.state === "completed" && status.result) {
          openResult(status.result);
          setState("completed");
        } else if (status.state === "completed") {
          setError({ message: "The server finished but sent no results.", retryable: true });
          setState("failed");
        } else if (status.state === "failed") {
          setError({ message: status.error ?? "The analysis server reported a failure.", retryable: true });
          setState("failed");
        } else {
          setState(status.state);
        }
      } catch (err) {
        if (isAbort(err)) return;
        if (err instanceof ApiError && err.status === 404) {
          // Deleted, or not this account's: start fresh instead of retrying.
          setSessionId(null);
          setState("no_video");
          setNotice("That recording no longer exists, so a new review has been started.");
          window.history.replaceState(null, "", "/review");
          return;
        }
        errorsInARow += 1;
        if (errorsInARow >= MAX_POLL_ERRORS) {
          setError(toErrorInfo(err));
          setState("failed");
        }
      }
    };

    poll(); // right away, so a reopened recording shows its state without waiting
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [sessionId, state, openResult]);

  async function cancelAnalysis() {
    if (state === "uploading") {
      uploadAbort.current?.abort(); // startAnalysis() moves to "canceled"
      return;
    }
    setState("canceled"); // stops polling right away
    if (sessionId) {
      try {
        await cancelJob(sessionId);
      } catch {
        setCancelNote("The server didn’t confirm it stopped. The job may still finish in the background.");
      }
    }
  }

  // ---------- Demonstration ----------

  /** Load the bundled MM-OR clip and send it to the backend like any upload. */
  async function analyzeSampleVideo() {
    setError(null);
    try {
      const res = await fetch(SAMPLE_VIDEO_SRC);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const sample = new File([await res.blob()], SAMPLE_VIDEO_SRC.split("/").pop() ?? "demo.mp4", {
        type: "video/mp4",
      });
      setLocalVideo(sample);
      setDetails(SAMPLE_DETAILS);
      await startAnalysis(sample, SAMPLE_DETAILS);
    } catch {
      setError({ message: "The demo video could not be loaded. Please try again.", retryable: true });
      setState("failed");
    }
  }

  function openDemo() {
    setDemo(true);
    clearReport();
    openResult(DEMO_RESULT);
  }

  function leaveDemo() {
    setDemo(false);
    setResult(null);
    setFindings([]);
    setSelectedId(null);
    setDuration(0);
    clearReport();
    // Drop "?demo=1" so a refresh doesn't reopen the demonstration.
    window.history.replaceState(null, "", "/review");
  }

  // ---------- Review ----------

  function seek(seconds: number) {
    const video = videoRef.current;
    if (video) video.currentTime = seconds;
    setCurrentTime(seconds);
  }

  function selectFinding(eventId: string) {
    setSelectedId(eventId);
    const finding = findings.find((f) => f.eventId === eventId);
    if (finding) seek(finding.timestampSec);
  }

  function persist(eventId: string, status: ReviewStatus) {
    if (!result || result.source !== "backend") return; // demo decisions stay in this tab
    setSyncState("saving");
    saveReviewDecision(result.sessionId, eventId, status)
      .then(() => setSyncState("saved"))
      .catch(() => setSyncState("error"));
  }

  function decide(eventId: string, status: ReviewStatus) {
    const current = findings.find((f) => f.eventId === eventId);
    if (!current) return;
    setPrevious((p) => ({ ...p, [eventId]: current.reviewStatus }));
    setFindings((all) => all.map((f) => (f.eventId === eventId ? { ...f, reviewStatus: status } : f)));
    persist(eventId, status);
  }

  function undo(eventId: string) {
    const before = previous[eventId];
    if (!before) return;
    setFindings((all) => all.map((f) => (f.eventId === eventId ? { ...f, reviewStatus: before } : f)));
    setPrevious((p) => {
      const rest = { ...p };
      delete rest[eventId];
      return rest;
    });
    persist(eventId, before);
  }

  // ---------- Final report ----------

  const snapshotOf = (list: Finding[]) => Object.fromEntries(list.map((f) => [f.eventId, f.reviewStatus]));

  function clearReport() {
    setReport(null);
    setReportStatus("idle");
    setReportError(null);
    setReportSnapshot({});
  }

  // A backend recording may already have a saved report: load it once its results arrive.
  const loadedReportFor = useRef<string | null>(null);
  useEffect(() => {
    if (!result || result.source !== "backend" || loadedReportFor.current === result.sessionId) return;
    loadedReportFor.current = result.sessionId;
    const list = result.findings;
    getReport(result.sessionId, list)
      .then((saved) => {
        if (saved) {
          setReport(saved);
          setReportSnapshot(snapshotOf(list));
        }
      })
      .catch(() => {}); // no saved report shown; writing a new one still works
  }, [result]);

  async function writeOrShowReport() {
    if (!result) return;
    setReportError(null);
    if (result.source === "demo") {
      setReport(demoReport(findings));
      setReportSnapshot(snapshotOf(findings));
      return;
    }
    const decisionsAtStart = snapshotOf(findings);
    setReportStatus("writing");
    try {
      const written = await writeReport(result.sessionId, findings);
      setReport(written);
      setReportSnapshot(decisionsAtStart);
      setReportStatus("idle");
    } catch (err) {
      setReportError(err instanceof ApiError ? err.message : "The report couldn’t be written. Please try again.");
      setReportStatus("error");
    }
  }

  function jumpToFinding(eventId: string) {
    selectFinding(eventId);
    document.getElementById("video-player")?.scrollIntoView({ block: "center" });
  }

  const reportStale =
    report !== null && (report.stale || findings.some((f) => reportSnapshot[f.eventId] !== f.reviewStatus));

  // ---------- Exports ----------

  function exportSlug() {
    const name = demo ? DEMO_DETAILS.name : details.name;
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "session";
    return `rescrub-review-${slug}-${new Date().toISOString().slice(0, 10)}`;
  }

  /** Opens the print dialog on the review document (PrintableReview); choose "Save as PDF". */
  function exportPdf() {
    const before = document.title;
    document.title = exportSlug(); // browsers use the title as the PDF file name
    const restore = () => {
      document.title = before;
      window.removeEventListener("afterprint", restore);
    };
    window.addEventListener("afterprint", restore);
    window.print();
  }

  function exportReview() {
    if (!result) return;
    const sessionDetails = demo ? DEMO_DETAILS : details;
    const payload = {
      exportedAt: new Date().toISOString(),
      app: "reScrub",
      notice:
        result.source === "demo"
          ? "Demonstration data on a synthetic clip. This is not a review of a real procedure."
          : "AI-proposed moments with human reviewer decisions. Not a determination that contamination occurred.",
      source: result.source,
      session: {
        sessionId: result.sessionId,
        name: sessionDetails.name,
        procedureContext: sessionDetails.procedureContext,
        recording: {
          fileName: demo ? DEMO_VIDEO_SRC.split("/").pop() : file ? displayFileName(file.name) : undefined,
          durationSec: Number(duration.toFixed(2)),
        },
      },
      findings,
      ...(report ? { report: { ...report, staleWhenExported: reportStale } } : {}),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = `${exportSlug()}.json`;
    link.click();
    URL.revokeObjectURL(href);
  }

  // ---------- Reset ----------

  async function deleteFromServer() {
    if (!result || result.source !== "backend") return;
    const ok = window.confirm(
      "Delete this recording, its labeled video, tracking data and findings from the server? This can’t be undone.",
    );
    if (!ok) return;
    try {
      await deleteRecording(result.sessionId);
      newReview();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "The recording could not be deleted. Please try again.");
    }
  }

  function newReview() {
    const hasDecisions = !demo && findings.some((f) => f.reviewStatus !== "needs_review");
    if (hasDecisions && !window.confirm("Start a new review? Decisions you haven’t exported will be cleared from this page.")) {
      return;
    }
    uploadAbort.current?.abort();
    if (sessionId && (state === "queued" || state === "analyzing")) {
      cancelJob(sessionId).catch(() => {}); // best effort
    }
    setLocalVideo(null);
    setDetails(EMPTY_DETAILS);
    setSessionId(null);
    setAnalysisProgress(null);
    setQueuePosition(null);
    setNotice(null);
    setCancelNote(null);
    window.history.replaceState(null, "", "/review");
    setDemo(false);
    setResult(null);
    setFindings([]);
    setPrevious({});
    setSelectedId(null);
    setCurrentTime(0);
    setDuration(0);
    setSyncState("idle");
    clearReport();
    loadedReportFor.current = null;
    window.scrollTo({ top: 0 });
  }

  // ---------- Render ----------

  const inReview = demo || (state === "completed" && result != null);

  if (inReview && result) {
    const selectedIndex = findings.findIndex((f) => f.eventId === selectedId);
    const selected = selectedIndex >= 0 ? findings[selectedIndex] : null;
    const storageNote =
      result.source === "demo"
        ? "Sample data. Decisions stay in this tab only."
        : {
            idle: "Decisions will be sent to the server as you make them.",
            saving: "Saving decision…",
            saved: "Decisions saved to the server.",
            error: "Last decision wasn’t saved to the server. Export to keep a copy.",
          }[syncState];

    const sessionName = demo ? DEMO_DETAILS.name : details.name;
    const shownFileName = demo ? "demo-procedure.webm" : file ? displayFileName(file.name) : "Recording";

    return (
      <>
        {/* The whole screen view is hidden when printing; PrintableReview is printed instead. */}
        <div className="contents print:hidden">
        <AppHeader onNewReview={newReview} account={account ?? undefined} />
        {demo ? (
          <div className="border-b border-amber-mark/40 bg-amber-soft">
            <div className="mx-auto flex max-w-[1400px] flex-col gap-2 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-amber">
                <span className="eyebrow rounded-[2px] bg-amber-mark/30 px-2 py-1 text-amber">[ Demonstration ]</span>
                Sample findings on a synthetic clip. Nothing was uploaded or analyzed.
              </p>
              <button
                type="button"
                className="eyebrow shrink-0 self-start text-amber underline underline-offset-4 sm:self-auto"
                onClick={leaveDemo}
              >
                Leave demonstration
              </button>
            </div>
          </div>
        ) : (
          <div className="border-b border-line bg-surface-sunken">
            <p className="mx-auto max-w-[1400px] px-4 py-2.5 text-sm text-ink-muted sm:px-6">
              <span className="eyebrow mr-2 text-ink-faint">AI-proposed</span>
              These moments are suggestions for human review. They don’t establish that contamination
              occurred.
              {(result.discardedFindings ?? 0) > 0 && (
                <span className="mt-1 block text-amber">
                  {result.discardedFindings} proposed{" "}
                  {result.discardedFindings === 1 ? "finding was" : "findings were"} left out because the
                  server sent {result.discardedFindings === 1 ? "it" : "them"} in an invalid format. Watch
                  the full recording rather than relying on this list.
                </span>
              )}
            </p>
          </div>
        )}
        <main className="mx-auto w-full max-w-[1400px] space-y-5 px-4 py-6 sm:px-6 sm:py-8">

          <ReviewSummary
            sessionName={sessionName}
            fileName={shownFileName}
            durationSec={duration}
            source={result.source}
            findings={findings}
            storageNote={storageNote}
            onExport={exportReview}
            onExportPdf={exportPdf}
            onDelete={result.source === "backend" ? deleteFromServer : undefined}
            labeledVideoUrl={result.source === "backend" ? result.annotatedVideoUrl : undefined}
          />

          {/* Desktop: video + timeline + evidence on the left (2/3), findings on the right (1/3).
              Mobile: video, timeline, findings, then evidence. */}
          <div className="grid gap-4 [grid-template-areas:'player'_'timeline'_'findings'_'chain'] lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)] lg:grid-rows-[auto_auto_1fr] lg:[grid-template-areas:'player_findings'_'timeline_findings'_'chain_findings']">
            <div id="video-player" className="[grid-area:player]">
              <VideoPlayer
                src={demo ? DEMO_VIDEO_SRC : (result.annotatedVideoUrl ?? videoUrl ?? "")}
                videoRef={videoRef}
                currentTime={currentTime}
                duration={duration}
                onTimeChange={setCurrentTime}
                onDuration={setDuration}
                title={demo ? "demo-procedure.webm" : file ? displayFileName(file.name) : "recording"}
                badge={demo ? "Synthetic clip" : result.annotatedVideoUrl ? "Labeled by analysis" : "Local playback"}
              />
            </div>
            <div className="[grid-area:timeline]">
              <EventTimeline
                findings={findings}
                duration={duration}
                currentTime={currentTime}
                selectedId={selectedId}
                onSelect={selectFinding}
                onSeek={seek}
              />
            </div>
            <div className="[grid-area:chain]">
              <ContactChain finding={selected} number={selectedIndex + 1} currentTime={currentTime} onSeek={seek} />
            </div>
            <div className="[grid-area:findings] lg:sticky lg:top-4 lg:self-start">
              <FindingsPanel
                findings={findings}
                selectedId={selectedId}
                currentTime={currentTime}
                undoable={new Set(Object.keys(previous))}
                onSelect={selectFinding}
                onDecide={decide}
                onUndo={undo}
              />
            </div>
          </div>

          <ReportPanel
            report={report}
            source={result.source}
            status={reportStatus}
            error={reportError}
            stale={reportStale}
            onWrite={writeOrShowReport}
            onJump={jumpToFinding}
          />
        </main>
        <SiteFooter />
        </div>

        <PrintableReview
          sessionName={sessionName}
          fileName={shownFileName}
          durationSec={duration}
          source={result.source}
          findings={findings}
          report={report}
          reportStale={reportStale}
        />
      </>
    );
  }

  const jobState =
    state === "uploading" || state === "queued" || state === "analyzing" || state === "failed" || state === "canceled"
      ? state
      : null;
  const locked = state === "uploading" || state === "queued" || state === "analyzing";

  return (
    <>
      <AppHeader onNewReview={newReview} account={account ?? undefined} />
      <main className="mx-auto w-full max-w-[1240px] px-4 sm:px-6">
        {/* Compact introduction: the numbered steps below stay the visual focus. */}
        <section className="flex flex-col gap-4 border-b border-line py-7 sm:flex-row sm:items-end sm:justify-between sm:py-9">
          <div>
            <p className="eyebrow text-accent">New review</p>
            <h1 className="font-display mt-2 text-[30px] leading-[1.1] tracking-[-0.01em] sm:text-[38px]">
              Bring the procedure into focus.
            </h1>
            <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-ink-muted">
              Add a recording and a little context below, then step through each flagged moment
              beside the video.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-3 self-start sm:self-auto">
            {isBackendConfigured && (
              <button
                type="button"
                onClick={analyzeSampleVideo}
                disabled={locked}
                className={buttonStyles.primary}
                title="Upload a 3-minute MM-OR surgery clip and analyze it"
              >
                Analyze demo video
              </button>
            )}
            <button type="button" onClick={openDemo} disabled={locked} className={buttonStyles.secondary}>
              View demonstration
            </button>
          </div>
        </section>

        {notice && (
          <p role="status" className="mt-6 border-l-2 border-amber-mark bg-amber-soft px-4 py-3 text-[15px]">
            {notice}
          </p>
        )}

        {/* Setup: steps first (also first on phones), explanation beside them on desktop. */}
        <section className="grid gap-10 py-10 sm:py-12 lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)] lg:gap-14">
            <SessionSetup
              details={details}
              hasFile={file != null}
              locked={locked}
              onChange={(patch) => setDetails((d) => ({ ...d, ...patch }))}
              onAnalyze={() => startAnalysis()}
              recording={
                !file && sessionId && state !== "no_video" ? (
                  // Reopened from /review?session=…: the video is on the server, not in this browser.
                  <div className="rounded-[3px] border border-line bg-surface px-4 py-3.5 text-[15px]">
                    <p className="font-medium">{details.name || "Your recording"}</p>
                    <p className="mt-1 text-ink-muted">
                      Already uploaded. Its analysis status is below; the review opens here when it finishes.
                    </p>
                  </div>
                ) : (
                  <VideoUpload
                    file={file}
                    videoUrl={videoUrl}
                    durationSec={previewDuration}
                    locked={locked}
                    onFileChosen={setLocalVideo}
                    onRemove={() => setLocalVideo(null)}
                    onDuration={setPreviewDuration}
                  />
                )
              }
              status={
                jobState && (
                  <AnalysisStatus
                    state={jobState}
                    uploadProgress={uploadProgress}
                    error={error}
                    cancelNote={cancelNote}
                    analysisProgress={analysisProgress}
                    queuePosition={queuePosition}
                    canRetry={file != null}
                    onCancel={cancelAnalysis}
                    onRetry={() => startAnalysis()}
                    onBack={file ? () => setState("ready") : newReview}
                  />
                )
              }
            />

            <aside aria-labelledby="video-goes-heading" className="lg:sticky lg:top-6 lg:self-start">
              <RecentRecordings currentSessionId={sessionId} />
              <h2 id="video-goes-heading" className="font-display text-[26px] leading-tight tracking-[-0.01em]">
                Where your video goes
              </h2>
              <ul className="mt-5 divide-y divide-line border-y border-line text-[15px] leading-relaxed">
                <li className="py-3.5">
                  <span className="eyebrow block text-ink-faint">Before analysis</span>
                  Your video previews locally in this browser. Nothing is uploaded.
                </li>
                <li className="py-3.5">
                  <span className="eyebrow flex items-center gap-2 text-ink-faint">
                    During analysis
                    {!isBackendConfigured && (
                      <span className="rounded-[2px] bg-amber-soft px-1.5 py-0.5 text-amber">Not connected</span>
                    )}
                  </span>
                  {isBackendConfigured ? (
                    <>
                      When you choose Analyze, the video and session details are uploaded to the
                      reScrub servers, which label people anonymously, track hands and surfaces,
                      and propose findings. Only your account can see the results.
                    </>
                  ) : (
                    <>
                      Analysis isn’t connected on this site, so nothing is uploaded. Open the
                      demonstration to see a finished review.
                    </>
                  )}
                </li>
                <li className="py-3.5">
                  <span className="eyebrow block text-ink-faint">After analysis</span>
                  An instructor confirms or dismisses each proposed finding. Model flags are
                  suggestions, not clinical determinations.
                </li>
              </ul>
              <p className="mt-4 text-sm text-ink-muted">
                Details in{" "}
                <Link href="/privacy" className="text-accent underline underline-offset-2">
                  Privacy
                </Link>
                .
              </p>
            </aside>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
