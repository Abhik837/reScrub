import Image from "next/image";
import Link from "next/link";
import type { Account } from "@/lib/auth";
import { AccountNav } from "./AccountNav";
import { buttonStyles } from "./ui";

/** The reScrub logo mark (public/brand/rescrub-mark.png) with the wordmark. */
export function Wordmark({ onDark = false }: { onDark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      {/* The mark is nearly square (127×128); shown at 26px tall, never stretched. */}
      <Image src="/brand/rescrub-mark.png" alt="" width={26} height={26} className="h-[26px] w-auto" priority />
      <span className={`font-display text-[22px] leading-none tracking-[-0.015em] ${onDark ? "text-white" : "text-ink"}`}>
        reScrub
      </span>
    </span>
  );
}

interface AppHeaderProps {
  /** On the review workspace, "New review" resets the page. Elsewhere it links to /review. */
  onNewReview?: () => void;
  /** Known signed-in account (from the server); otherwise the header asks the API itself. */
  account?: Account | null;
}

const navLink =
  "whitespace-nowrap rounded-[3px] px-1.5 py-2 text-[14px] text-ink-muted underline-offset-4 hover:text-ink hover:underline sm:px-2";

export function AppHeader({ onNewReview, account }: AppHeaderProps) {
  return (
    <header className="border-b border-line bg-canvas/95">
      <div className="mx-auto flex h-16 max-w-[1240px] items-center gap-2 px-4 sm:gap-3 sm:px-6">
        <Link href="/" className="rounded-[3px]" aria-label="reScrub home">
          <Wordmark />
        </Link>
        <span className="eyebrow ml-1 hidden rounded-[2px] border border-accent-mark/60 bg-accent-soft px-1.5 py-0.5 text-accent md:inline">
          Training tool
        </span>

        <nav className="ml-auto flex items-center gap-0.5 sm:gap-2" aria-label="Main">
          <Link href="/#how-it-works" className={`${navLink} hidden sm:inline`}>
            How it works
          </Link>
          <AccountNav initial={account ?? undefined} />
          {onNewReview ? (
            <button type="button" onClick={onNewReview} className={`${buttonStyles.primary} whitespace-nowrap px-3 sm:px-4`}>
              New review
            </button>
          ) : (
            <Link href="/review" className={`${buttonStyles.primary} whitespace-nowrap px-3 sm:px-4`}>
              New review
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
