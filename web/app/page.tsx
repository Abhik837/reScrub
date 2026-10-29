import Image from "next/image";
import Link from "next/link";
import { AppHeader } from "@/components/AppHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { buttonStyles } from "@/components/ui";
import { isBackendConfigured } from "@/lib/api";

// Licensed under the Unsplash License. Credit and details: docs/ASSETS.md
const HERO_PHOTO = "https://images.unsplash.com/photo-1728102199887-a285f8957c5d";

const STEPS = [
  {
    title: "Upload a recording",
    body: "Add an MP4 of a practice procedure. It previews in your browser before anything is sent.",
  },
  {
    title: "Review flagged moments",
    body: "Jump straight to each moment the analysis proposes, on a timeline beside the video.",
  },
  {
    title: "Confirm the evidence",
    body: "Watch each contact chain, then confirm or dismiss it. The final call is always yours.",
  },
];

export default function HomePage() {
  return (
    <>
      <AppHeader />
      <main className="w-full">
        {/* Opening */}
        <section className="mx-auto grid max-w-[1240px] items-center gap-10 px-4 py-12 sm:px-6 sm:py-16 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:gap-16 lg:py-20">
          <div>
            <p className="eyebrow text-accent">Sterile-technique review</p>
            <h1 className="font-display mt-4 text-[44px] leading-[1.02] tracking-[-0.02em] sm:text-[60px] lg:text-[68px]">
              A second look at sterile technique.
            </h1>
            <p className="mt-6 max-w-lg text-[18px] leading-relaxed text-ink-muted">
              Review procedure recordings, investigate possible breaks in technique, and turn
              flagged moments into training.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/review" className={`${buttonStyles.primary} min-h-11 px-6`}>
                New review
              </Link>
              <Link href="/review?demo=1" className={`${buttonStyles.secondary} min-h-11 px-6`}>
                View demonstration
              </Link>
            </div>
          </div>

          <figure>
            <div className="relative aspect-[4/5] overflow-hidden rounded-[3px] border border-line bg-surface-sunken sm:aspect-[5/4] lg:aspect-[4/5]">
              <Image
                src={HERO_PHOTO}
                alt="A blue-gloved hand reaching for a steel instrument laid out with others on a pale surface."
                fill
                priority
                sizes="(min-width: 1024px) 520px, 100vw"
                className="object-cover object-[50%_30%]"
              />
            </div>
            <figcaption className="mt-2 text-xs text-ink-faint">
              Illustrative photo, not analysis output. Photo by{" "}
              <a
                href="https://unsplash.com/@subspace_stills?utm_source=rescrub&utm_medium=referral"
                className="underline underline-offset-2 hover:text-ink"
              >
                syahmi syahir
              </a>{" "}
              on{" "}
              <a
                href="https://unsplash.com/photos/a-hand-in-a-blue-glove-is-pointing-at-a-set-of-surgical-instruments-bmNzLUhu9Xo?utm_source=rescrub&utm_medium=referral"
                className="underline underline-offset-2 hover:text-ink"
              >
                Unsplash
              </a>
              .
            </figcaption>
          </figure>
        </section>

        {/* How it works */}
        <section id="how-it-works" aria-labelledby="how-heading" className="scroll-mt-6 border-t border-line">
          <div className="mx-auto max-w-[1240px] px-4 py-12 sm:px-6 sm:py-16">
            <h2 id="how-heading" className="font-display text-[32px] leading-tight tracking-[-0.01em] sm:text-[38px]">
              How it works
            </h2>
            <ol className="mt-8 grid gap-px overflow-hidden rounded-[3px] border border-line bg-line md:grid-cols-3">
              {STEPS.map((step, i) => (
                <li key={step.title} className="bg-surface p-6">
                  <p className="eyebrow flex items-center gap-2 text-accent">
                    <span className="flex size-6 items-center justify-center rounded-[2px] border border-accent-mark text-[10px] tracking-normal">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    {i < STEPS.length - 1 && (
                      <span aria-hidden="true" className="text-ink-faint">
                        →
                      </span>
                    )}
                  </p>
                  <h3 className="mt-4 text-[17px] font-semibold tracking-[-0.01em]">{step.title}</h3>
                  <p className="mt-2 text-[15px] leading-relaxed text-ink-muted">{step.body}</p>
                </li>
              ))}
            </ol>

            {/* What the tool does and doesn't do */}
            <div className="mt-8 flex flex-col gap-2 rounded-r-[3px] border border-l-2 border-line border-l-accent-mark bg-accent-soft/60 px-4 py-3.5 sm:flex-row sm:items-start sm:gap-4">
              <p className="eyebrow shrink-0 pt-0.5 text-accent">For training</p>
              <p className="text-[14px] leading-relaxed text-ink-muted">
                reScrub is for education. It suggests moments for a person to review; it does not
                detect microbes, certify sterility, or establish that contamination occurred.{" "}
                {isBackendConfigured
                  ? "Use simulated or properly de-identified footage you’re allowed to share."
                  : "Automated analysis isn’t connected on this site, so only the demonstration shows findings."}
              </p>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
