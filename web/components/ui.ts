// Shared button styles so every button looks and behaves the same.
// Usage: <button className={buttonStyles.primary}>Analyze</button>

const base =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-[3px] px-4 text-sm font-medium disabled:cursor-not-allowed";

export const buttonStyles = {
  primary: `${base} bg-primary text-white hover:bg-primary-hover disabled:bg-line-strong disabled:text-ink-muted`,
  secondary: `${base} border border-primary/70 bg-transparent text-primary hover:border-primary hover:bg-primary-soft disabled:border-line-strong disabled:text-ink-faint disabled:hover:bg-transparent`,
  ghost: `${base} text-ink-muted underline-offset-4 hover:text-ink hover:underline disabled:text-ink-faint`,
  /** Light-on-dark outline button for dark bands. */
  onDark: `${base} border border-white/70 text-white hover:bg-white hover:text-ink`,
  /** Smaller buttons used inside finding rows. */
  small:
    "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-[3px] border border-line-strong bg-surface px-3 text-[13px] font-medium text-ink hover:border-primary hover:text-primary",
};

/** A small status chip with a colored dot, e.g. ● NEEDS REVIEW */
export const chip = "eyebrow inline-flex items-center gap-1.5 rounded-[2px] px-1.5 py-1";
