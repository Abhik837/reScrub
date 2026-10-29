"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { AuthNotConnectedError, isAuthConfigured, safeNextPath, signUp, type SignUpOptions, signUpOptions } from "@/lib/auth";
import { buttonStyles } from "./ui";

// Same minimum as the backend (backend/rescrub/auth.py), which also enforces it.
const MIN_PASSWORD = 12;

type Errors = { email?: string; password?: string; confirm?: string };

function validate(email: string, password: string, confirm: string, domains: string[]): Errors {
  const errors: Errors = {};
  const address = email.trim().toLowerCase();
  if (!address) errors.email = "Enter your email address.";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) errors.email = "Enter an email address like name@school.edu.";
  else if (domains.length && !domains.includes(address.split("@")[1])) {
    errors.email = `Use an email address at ${domains.join(", ")}.`;
  }
  if (password.length < MIN_PASSWORD) errors.password = `Use at least ${MIN_PASSWORD} characters.`;
  if (confirm !== password) errors.confirm = "The passwords don’t match.";
  return errors;
}

const fieldClass =
  "w-full rounded-[3px] border border-line-strong bg-surface px-3 py-2.5 text-[15px] text-ink placeholder:text-ink-faint hover:border-ink-faint focus:border-primary aria-[invalid=true]:border-flag-mark";

export function SignUpForm({ next }: { next?: string }) {
  const [options, setOptions] = useState<SignUpOptions | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [submitted, setSubmitted] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const domains = options?.emailDomains ?? [];
  const signInHref = next ? `/login?next=${encodeURIComponent(next)}` : "/login";

  useEffect(() => {
    let live = true;
    signUpOptions().then((o) => live && setOptions(o));
    return () => {
      live = false;
    };
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    const found = validate(email, password, confirm, domains);
    setErrors(found);
    if (found.email) return emailRef.current?.focus();
    if (found.password) return passwordRef.current?.focus();
    if (found.confirm) return confirmRef.current?.focus();

    setBusy(true);
    setOutcome(null);
    try {
      await signUp({ email: email.trim(), password });
      setOutcome("Account created. Opening your workspace…");
      // A full navigation so the server sees the new sign-in cookie.
      window.location.assign(safeNextPath(next));
    } catch (err) {
      // The server checks the address against its provider's rules and DNS; show that beside the field.
      if (err instanceof ApiError && err.status && [400, 403, 409].includes(err.status) && !/password|characters/i.test(err.message)) {
        setErrors({ email: err.message });
        setBusy(false);
        setOutcome(null);
        setPassword("");
        setConfirm("");
        emailRef.current?.focus();
        return;
      }
      setOutcome(
        err instanceof AuthNotConnectedError
          ? "Sign-up isn’t connected, so no account was created. Nothing you entered was sent or saved."
          : err instanceof ApiError
            ? err.message
            : "The account could not be created. Please try again.",
      );
      setBusy(false);
      // Never keep passwords around after a failed attempt.
      setPassword("");
      setConfirm("");
    }
  }

  function update(nextEmail: string, nextPassword: string, nextConfirm: string) {
    if (submitted) setErrors(validate(nextEmail, nextPassword, nextConfirm, domains));
  }

  if (options === null) {
    return <p className="text-[14px] text-ink-muted">Loading…</p>;
  }

  if (!options.open) {
    return (
      <div className="space-y-5">
        <div className="rounded-r-[3px] border border-l-2 border-line border-l-amber-mark bg-amber-soft px-4 py-3">
          <p className="eyebrow text-amber">Sign-up closed</p>
          <p className="mt-1 text-[14px] leading-relaxed text-ink">
            {isAuthConfigured
              ? "This site doesn’t let people create their own accounts. Ask its administrator for one."
              : "This copy of the site isn’t connected to the analysis server, so accounts can’t be created. The demonstration still works."}
          </p>
        </div>
        <Link href={signInHref} className={`${buttonStyles.secondary} min-h-11 w-full`}>
          Sign in
        </Link>
      </div>
    );
  }

  const describe = (id: string, error?: string) => (error ? `${id}-error` : undefined);

  return (
    <form noValidate onSubmit={onSubmit} aria-labelledby="signup-heading" className="space-y-5">
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
            update(e.target.value, password, confirm);
          }}
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={describe("email", errors.email) ?? (domains.length ? "email-hint" : undefined)}
          className={fieldClass}
        />
        {errors.email ? (
          <p id="email-error" className="mt-1.5 text-[13px] text-flag">
            {errors.email}
          </p>
        ) : (
          domains.length > 0 && (
            <p id="email-hint" className="mt-1.5 text-[13px] text-ink-muted">
              Use your address at {domains.join(", ")}.
            </p>
          )
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
            autoComplete="new-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              update(email, e.target.value, confirm);
            }}
            aria-invalid={errors.password ? true : undefined}
            aria-describedby={describe("password", errors.password) ?? "password-hint"}
            className={`${fieldClass} pr-20`}
          />
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            aria-controls="password confirm"
            aria-pressed={showPassword}
            className="absolute inset-y-1 right-1 rounded-[2px] px-2.5 text-[13px] font-medium text-primary hover:bg-primary-soft"
          >
            {showPassword ? "Hide" : "Show"}
            <span className="sr-only"> passwords</span>
          </button>
        </div>
        {errors.password ? (
          <p id="password-error" className="mt-1.5 text-[13px] text-flag">
            {errors.password}
          </p>
        ) : (
          <p id="password-hint" className="mt-1.5 text-[13px] text-ink-muted">
            At least {MIN_PASSWORD} characters. A few unrelated words work well.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="confirm" className="mb-1.5 block text-sm font-medium">
          Confirm password
        </label>
        <input
          ref={confirmRef}
          id="confirm"
          type={showPassword ? "text" : "password"}
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => {
            setConfirm(e.target.value);
            update(email, password, e.target.value);
          }}
          aria-invalid={errors.confirm ? true : undefined}
          aria-describedby={describe("confirm", errors.confirm)}
          className={fieldClass}
        />
        {errors.confirm && (
          <p id="confirm-error" className="mt-1.5 text-[13px] text-flag">
            {errors.confirm}
          </p>
        )}
      </div>

      <button type="submit" disabled={busy} className={`${buttonStyles.primary} min-h-11 w-full`}>
        {busy ? "Creating account…" : "Create account"}
      </button>

      <p className="text-[13px] text-ink-muted">
        By creating an account you agree to the{" "}
        <Link href="/terms" className="underline underline-offset-2 hover:text-ink">
          terms
        </Link>{" "}
        and{" "}
        <Link href="/privacy" className="underline underline-offset-2 hover:text-ink">
          privacy notice
        </Link>
        .
      </p>

      <p role="status" aria-live="polite" className={outcome ? "text-[14px] text-amber" : "sr-only"}>
        {outcome ?? ""}
      </p>

      <p className="border-t border-line pt-5 text-center text-[14px] text-ink-muted">
        Already have an account?{" "}
        <Link href={signInHref} className="font-medium text-primary underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
