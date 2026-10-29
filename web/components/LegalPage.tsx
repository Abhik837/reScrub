import Link from "next/link";
import type { ReactNode } from "react";
import { AppHeader } from "./AppHeader";
import { SiteFooter } from "./SiteFooter";

/** Wraps the Terms and Privacy pages with the same header, width, and type styles. */
export function LegalPage({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: ReactNode;
}) {
  return (
    <>
      <AppHeader />
      <main className="mx-auto w-full max-w-[720px] px-4 py-10 sm:px-6">
        <nav aria-label="Legal pages" className="mb-8 flex gap-5">
          <Link href="/terms" className="eyebrow text-accent underline-offset-4 hover:underline">
            Terms
          </Link>
          <Link href="/privacy" className="eyebrow text-accent underline-offset-4 hover:underline">
            Privacy
          </Link>
        </nav>
        <h1 className="font-display text-[44px] leading-[1.05] tracking-[-0.02em] sm:text-[56px]">{title}</h1>
        <p className="eyebrow mt-4 text-ink-faint">Last updated {updated}</p>
        <div className="mt-8 space-y-8 text-[15px] leading-relaxed [&_h2]:mb-2 [&_h2]:text-lg [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_li]:pl-1 [&_p+p]:mt-3 [&_ul]:mt-2 [&_ul]:space-y-1.5">
          {children}
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
