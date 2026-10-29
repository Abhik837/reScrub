import { cleanText } from "./validate";

/** 75.4 → "01:15.4" */
export function formatTimestamp(totalSeconds: number): string {
  const safe = Number.isFinite(totalSeconds) ? Math.max(0, totalSeconds) : 0;
  const minutes = Math.floor(safe / 60);
  const seconds = safe - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(1).padStart(4, "0")}`;
}

/** 75 → "1:15" (for durations, without tenths) */
export function formatDuration(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds)) return "–";
  const s = Math.round(totalSeconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * A filename that's safe to show: no hidden control or text-direction characters
 * (which can disguise e.g. "evil‮webm.exe"), and not absurdly long.
 */
export function displayFileName(name: string): string {
  return cleanText(name, 120) ?? "recording";
}

/** 1536000 → "1.5 MB" */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${Number((bytes / 1024 / 1024).toFixed(1))} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
