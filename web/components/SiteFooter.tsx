import Link from "next/link";
import { Wordmark } from "./AppHeader";

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-line bg-surface-sunken">
      <div className="mx-auto grid max-w-[1240px] gap-6 px-4 py-10 sm:px-6 md:grid-cols-[1fr_auto]">
        <div className="max-w-xl">
          <Wordmark />
          <p className="mt-4 text-sm leading-relaxed text-ink-muted">
            reScrub is a training tool for sterile technique. It suggests moments for a person to
            review. It does not detect microbes, certify sterility, or establish that contamination
            occurred.
          </p>
        </div>
        <nav aria-label="Legal" className="flex gap-6 md:flex-col md:items-end md:gap-2">
          <Link href="/terms" className="eyebrow text-ink-muted hover:text-ink">
            Terms
          </Link>
          <Link href="/privacy" className="eyebrow text-ink-muted hover:text-ink">
            Privacy
          </Link>
        </nav>
      </div>
    </footer>
  );
}
