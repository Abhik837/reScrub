"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { AuthNotConnectedError, isAuthConfigured, safeNextPath, signIn } from "@/lib/auth";
import { buttonStyles } from "./ui";

type Errors = { email?: string; password?: string };

function validate(email: string, password: string): Errors {
  const errors: Errors = {};
  if (!email.trim()) errors.email = "Enter your email address.";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) errors.email = "Enter an email address like name@school.edu.";
  if (!password) errors.password = "Enter your password.";
  return errors;
}

const fieldClass =
  "w-full rounded-[3px] border bg-surface px-3 py-2.5 text-[15px] text-ink placeholder:text-ink-faint hover:border-ink-faint focus:border-primary aria-[invalid=true]:border-flag-mark";

export function SignInForm({ next }: { next?: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [submitted, setSubmitted] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    const found = validate(email, password);
    setErrors(found);
    if (found.email) return emailRef.current?.focus();
    if (found.password) return passwordRef.current?.focus();

    setBusy(true);
    setOutcome(null);
    try {
      await signIn({ email: email.trim(), password });
      setOutcome("Signed in. Opening your workspace…");
      // A full navigation so the server sees the new sign-in cookie.
      window.location.assign(safeNextPath(next));
    } catch (err) {
      setOutcome(
        err instanceof AuthNotConnectedError
          ? "Sign-in isn’t connected, so you were not signed in. Nothing you entered was sent or saved."
          : err instanceof ApiError
            ? err.message
            : "Sign-in failed. Please try again.",
      );
      setBusy(false);
    } finally {
      // Never keep the password around after an attempt.
      setPassword("");
    }
  }

  // After the first submit, re-check as the person types so errors clear promptly.
  function update(nextEmail: string, nextPassword: string) {
    if (submitted) setErrors(validate(nextEmail, nextPassword));
  }

  return (
    <form noValidate onSubmit={onSubmit} aria-labelledby="signin-heading" className="space-y-5">
      {!isAuthConfigured && (
        <div className="rounded-r-[3px] border border-l-2 border-line border-l-amber-mark bg-amber-soft px-4 py-3">
          <p className="eyebrow text-amber">Not connected</p>
          <p className="mt-1 text-[14px] leading-relaxed text-ink">
            This copy of the site isn’t connected to the analysis server, so it can’t sign you in
            and nothing you type is sent or stored. The demonstration still works.
          </p>
        </div>
      )}

      <div>
        <label htmlFor="email" className="mb-1.5 block text-sm font-medium">
          Email
        </label>
        <input
          ref={emailRef}
          id="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            update(e.target.value, password);
          }}
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={errors.email ? "email-error" : undefined}
          className={`${fieldClass} border-line-strong`}
        />
        {errors.email && (
          <p id="email-error" className="mt-1.5 text-[13px] text-flag">
            {errors.email}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="password" className="mb-1.5 block text-sm font-medium">
          Password
        </label>
        <div className="relative">
          <input
            ref={passwordRef}
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              update(email, e.target.value);
            }}
            aria-invalid={errors.password ? true : undefined}
            aria-describedby={errors.password ? "password-error" : undefined}
            className={`${fieldClass} border-line-strong pr-20`}
          />
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            aria-controls="password"
            aria-pressed={showPassword}
            className="absolute inset-y-1 right-1 rounded-[2px] px-2.5 text-[13px] font-medium text-primary hover:bg-primary-soft"
          >
            {showPassword ? "Hide" : "Show"}
            <span className="sr-only"> password</span>
          </button>
        </div>
        {errors.password && (
          <p id="password-error" className="mt-1.5 text-[13px] text-flag">
            {errors.password}
          </p>
        )}
      </div>

      <button type="submit" disabled={busy} className={`${buttonStyles.primary} min-h-11 w-full`}>
        {busy ? "Signing in…" : "Sign in"}
      </button>

      <p className="text-[14px] text-ink-muted">
        New to reScrub?{" "}
        <Link
          href={next ? `/register?next=${encodeURIComponent(next)}` : "/register"}
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          Create an account
        </Link>
      </p>
      <p className="text-[13px] text-ink-muted">Forgot your password? Ask this site’s administrator to reset it.</p>

      <p role="status" aria-live="polite" className={outcome ? "text-[14px] text-amber" : "sr-only"}>
        {outcome ?? ""}
      </p>

      <div className="border-t border-line pt-5">
        <Link href="/review?demo=1" className={`${buttonStyles.secondary} min-h-11 w-full`}>
          Open the demonstration
        </Link>
        <p className="mt-2 text-center text-[13px] text-ink-muted">No account needed. It uses a synthetic clip.</p>
      </div>
    </form>
  );
}
