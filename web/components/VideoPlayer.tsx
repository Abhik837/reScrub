"use client";

import { useEffect, useState, type RefObject } from "react";
import { formatTimestamp } from "@/lib/format";

interface VideoPlayerProps {
  src: string;
  /** Shared with the workspace so the timeline and findings can seek the video. */
  videoRef: RefObject<HTMLVideoElement | null>;
  currentTime: number;
  duration: number;
  onTimeChange: (seconds: number) => void;
  onDuration: (seconds: number) => void;
  /** Shown in the player's title bar, e.g. the file name. */
  title: string;
  /** Optional tag on the right of the title bar, e.g. "Synthetic clip". */
  badge?: string;
}

const RATES = [0.5, 1, 1.5, 2];

const controlButton =
  "inline-flex size-10 items-center justify-center rounded-[2px] text-stage-text hover:bg-stage-line";

export function VideoPlayer({
  src,
  videoRef,
  currentTime,
  duration,
  onTimeChange,
  onDuration,
  title,
  badge,
}: VideoPlayerProps) {
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [rate, setRate] = useState(1);
  const [failed, setFailed] = useState(false);

  // If the video loaded its metadata before this component attached its handlers
  // (e.g. opening /review?demo=1 directly), read the duration now.
  useEffect(() => {
    const video = videoRef.current;
    if (video && video.readyState >= 1 && Number.isFinite(video.duration)) onDuration(video.duration);
  }, [videoRef, onDuration]);

  // While playing, read the time every animation frame so the playhead moves smoothly.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const video = videoRef.current;
      if (video) onTimeChange(video.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, videoRef, onTimeChange]);

  function togglePlay() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }

  function skip(seconds: number) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.min(Math.max(0, video.currentTime + seconds), video.duration || 0);
    onTimeChange(video.currentTime);
  }

  return (
    <section
      aria-label="Video player"
      className="on-stage overflow-hidden rounded-[3px] border border-stage-line bg-stage"
      tabIndex={0}
      onKeyDown={(e) => {
        // Only handle keys aimed at the player itself, not its buttons or the speed menu.
        if (e.target !== e.currentTarget) return;
        if (e.key === " " || e.key === "k") {
          e.preventDefault();
          togglePlay();
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          skip(-5);
        } else if (e.key === "ArrowRight") {
          e.preventDefault();
          skip(5);
        }
      }}
    >
      {/* Title bar */}
      <div className="flex items-center justify-between gap-3 border-b border-stage-line px-3 py-2">
        <p className="truncate font-mono text-xs text-stage-muted">rescrub · {title}</p>
        {badge && <span className="eyebrow shrink-0 rounded-[2px] bg-white/10 px-1.5 py-0.5 text-stage-text">{badge}</span>}
      </div>

      <div className="relative">
        <video
          ref={videoRef}
          src={src}
          muted={muted}
          playsInline
          preload="auto"
          className="aspect-video w-full cursor-pointer bg-stage"
          onClick={togglePlay}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onSeeked={(e) => onTimeChange(e.currentTarget.currentTime)}
          onTimeUpdate={(e) => {
            if (!playing) onTimeChange(e.currentTarget.currentTime);
          }}
          onLoadedMetadata={(e) => {
            setFailed(false);
            onDuration(e.currentTarget.duration);
          }}
          onError={() => setFailed(true)}
        />
        {failed && (
          <div
            role="alert"
            className="absolute inset-0 flex items-center justify-center bg-stage p-6 text-center text-sm text-stage-text"
          >
            This browser can’t play this recording. Re-export it as an H.264 MP4 and start a new
            review.
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1 border-t border-stage-line bg-stage-raised px-2 py-1.5">
        <button
          type="button"
          className={controlButton}
          onClick={togglePlay}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? (
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="3" y="2" width="3.5" height="12" fill="currentColor" />
              <rect x="9.5" y="2" width="3.5" height="12" fill="currentColor" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
            </svg>
          )}
        </button>
        <button type="button" className={`${controlButton} w-auto px-2 font-mono text-xs`} onClick={() => skip(-5)} aria-label="Back 5 seconds">
          −5s
        </button>
        <button type="button" className={`${controlButton} w-auto px-2 font-mono text-xs`} onClick={() => skip(5)} aria-label="Forward 5 seconds">
          +5s
        </button>

        <p className="tabular ml-2 font-mono text-[13px] text-stage-text" aria-live="off">
          {formatTimestamp(currentTime)}
          <span className="text-stage-muted"> / {formatTimestamp(duration)}</span>
        </p>

        <div className="ml-auto flex items-center gap-1">
          <label className="sr-only" htmlFor="playback-rate">
            Playback speed
          </label>
          <select
            id="playback-rate"
            value={rate}
            onChange={(e) => {
              const next = Number(e.target.value);
              setRate(next);
              if (videoRef.current) videoRef.current.playbackRate = next;
            }}
            className="h-9 rounded-[2px] border border-stage-line bg-stage px-2 font-mono text-xs text-stage-text"
          >
            {RATES.map((r) => (
              <option key={r} value={r}>
                {r}×
              </option>
            ))}
          </select>
          <button
            type="button"
            className={`${controlButton} eyebrow w-auto px-2 text-stage-muted`}
            onClick={() => setMuted((m) => !m)}
            aria-pressed={!muted}
          >
            {muted ? "Sound off" : "Sound on"}
          </button>
        </div>
      </div>
      <p className="sr-only">
        Keyboard: focus the player, then press Space to play or pause and the arrow keys to skip 5
        seconds.
      </p>
    </section>
  );
}
