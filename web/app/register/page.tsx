import type { Metadata } from "next";
import { AppHeader } from "@/components/AppHeader";
import { SignUpForm } from "@/components/SignUpForm";
import { SiteFooter } from "@/components/SiteFooter";

export const metadata: Metadata = { title: "Create account · reScrub" };

export default async function RegisterPage({ searchParams }: PageProps<"/register">) {
  const { next } = await searchParams;
  return (
    <>
      <AppHeader />
      <main className="mx-auto w-full max-w-[440px] px-4 py-12 sm:py-16">
        <p className="eyebrow text-accent">Account</p>
        <h1 id="signup-heading" className="font-display mt-2 text-[36px] leading-[1.1] tracking-[-0.01em] sm:text-[42px]">
          Create account
        </h1>
        <p className="mt-2 text-[15px] text-ink-muted">
          For instructors and trainees reviewing practice recordings. Your recordings are visible only to you.
        </p>
        <div className="mt-8">
          <SignUpForm next={typeof next === "string" ? next : undefined} />
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
