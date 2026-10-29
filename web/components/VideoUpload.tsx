"use client";

import { useRef, useState } from "react";
import { displayFileName, formatBytes, formatDuration } from "@/lib/format";
import { buttonStyles } from "./ui";

/** Friendly limit shown to users. The backend must enforce its own limit too. */
export const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
/** Same as the backend's MAX_VIDEO_SEC (60 minutes). */
export const MAX_VIDEO_MINUTES = 60;

/**
 * Quick checks before preview: extension/type, size, and the file's first bytes.
 * MP4 files have the "ftyp" marker at byte 4. These checks are a convenience for
 * the user and are easy to bypass; the backend must validate uploads itself.
 */
async function validate(file: File): Promise<string | null> {
  const name = displayFileName(file.name);
  const looksLikeMp4 = file.type === "video/mp4" || file.name.toLowerCase().endsWith(".mp4");
  if (!looksLikeMp4) return `“${name}” isn’t an MP4 file. Choose a .mp4 recording.`;
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES)
    return `That file is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`;
  try {
    const head = new Uint8Array(await file.slice(0, 12).arrayBuffer());
    const marker = String.fromCharCode(...head.slice(4, 8));
    if (marker !== "ftyp") return `“${name}” doesn’t look like a real MP4 video. Re-export it as an H.264 MP4.`;
  } catch {
    return "That file couldn’t be read. Try choosing it again.";
  }
  return null;
}

interface VideoUploadProps {
  file: File | null;
  videoUrl: string | null;
  durationSec: number | null;
  /** True while uploading/analyzing, so the file can't be swapped mid-job. */
  locked: boolean;
  onFileChosen: (file: File) => void;
  onRemove: () => void;
  onDuration: (seconds: number) => void;
}

export function VideoUpload({
  file,
  videoUrl,
  durationSec,
  locked,
  onFileChosen,
  onRemove,
  onDuration,
}: VideoUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [playbackError, setPlaybackError] = useState(false);

  async function accept(candidate: File | undefined) {
    if (!candidate) return;
    const problem = await validate(candidate);
    setError(problem);
    if (!problem) {
      setPlaybackError(false);
      onFileChosen(candidate);
    }
  }

  const fileInput = (
    <input
      ref={inputRef}
      id="video-file"
      type="file"
      accept="video/mp4,.mp4"
      aria-label="Choose an MP4 recording"
      tabIndex={-1}
      className="sr-only"
      disabled={locked}
      onChange={(e) => {
        accept(e.target.files?.[0]);
        e.target.value = ""; // allow choosing the same file again
      }}
    />
  );

  const errorMessage = error && (
    <p role="alert" className="mt-2 text-sm text-flag">
      {error}
    </p>
  );

  if (file && videoUrl) {
    return (
      <div>
        <div className="overflow-hidden rounded-[3px] border border-stage-line bg-stage">
          {/* Title bar, like a product window */}
          <div className="flex items-center justify-between gap-3 border-b border-stage-line px-3 py-2">
            <p className="truncate font-mono text-xs text-stage-muted" title={displayFileName(file.name)}>
              preview · {displayFileName(file.name)}
            </p>
            <span className="eyebrow shrink-0 text-stage-muted">Local only</span>
          </div>
          <div className="on-stage">
            {/* Native controls here: this is a quick preview, not the review player. */}
            <video
              src={videoUrl}
              controls
              muted
              playsInline
              preload="metadata"
              className="aspect-video w-full"
              onLoadedMetadata={(e) => onDuration(e.currentTarget.duration)}
              onError={() => setPlaybackError(true)}
            />
          </div>
        </div>

        {durationSec != null && durationSec > MAX_VIDEO_MINUTES * 60 && (
          <p role="alert" className="mt-2 border-l-2 border-amber-mark bg-amber-soft px-3 py-2 text-sm text-amber">
            This recording is {formatDuration(durationSec)}. Recordings can be up to {MAX_VIDEO_MINUTES}{" "}
            minutes; trim it or split it into parts.
          </p>
        )}

        {playbackError && (
          <p role="alert" className="mt-2 border-l-2 border-amber-mark bg-amber-soft px-3 py-2 text-sm text-amber">
            This browser can’t play this file. It may use a codec such as HEVC. Re-export it as an
            H.264 MP4 and try again.
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <dl className="flex gap-6">
            <div>
              <dt className="eyebrow text-ink-faint">Size</dt>
              <dd className="tabular mt-0.5 font-mono text-sm">{formatBytes(file.size)}</dd>
            </div>
            <div>
              <dt className="eyebrow text-ink-faint">Duration</dt>
              <dd className="tabular mt-0.5 font-mono text-sm">
                {durationSec == null ? "Reading…" : formatDuration(durationSec)}
              </dd>
            </div>
          </dl>
          <div className="flex gap-2">
            {fileInput}
            <button
              type="button"
              className={buttonStyles.secondary}
              disabled={locked}
              onClick={() => inputRef.current?.click()}
            >
              Replace
            </button>
            <button
              type="button"
              className={buttonStyles.ghost}
              disabled={locked}
              onClick={() => {
                setError(null);
                onRemove();
              }}
            >
              Remove
            </button>
          </div>
        </div>
        {errorMessage}
      </div>
    );
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          accept(e.dataTransfer.files?.[0]);
        }}
        className={`flex min-h-64 flex-col items-start justify-between gap-8 rounded-[3px] border border-dashed p-6 transition-colors sm:min-h-72 sm:p-8 ${
          dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-surface"
        }`}
      >
        <p className="eyebrow text-ink-faint">
          MP4 · up to {formatBytes(MAX_UPLOAD_BYTES)} · {MAX_VIDEO_MINUTES} min
        </p>
        <div>
          <p className="font-display text-[28px] leading-tight tracking-[-0.01em] sm:text-[32px]">
            Drop a recording here
          </p>
          <p className="mt-2 max-w-md text-[15px] text-ink-muted">
            Use simulated or properly de-identified footage you’re allowed to share. It plays from
            this device and isn’t uploaded until you choose to analyze it.
          </p>
        </div>
        <div>
          {fileInput}
          <button
            type="button"
            className={buttonStyles.secondary}
            disabled={locked}
            onClick={() => inputRef.current?.click()}
          >
            Choose file
          </button>
        </div>
      </div>
      {errorMessage}
    </div>
  );
}
