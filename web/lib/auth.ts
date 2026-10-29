// The ONE place the website talks to sign-in. The backend sets an HttpOnly cookie, so
// this code never sees or stores a token; passwords are sent once over HTTPS and dropped.
// See docs/SECURITY.md (repository root), "Accounts and sign-in".

import { ApiError, isBackendConfigured, request } from "./api";
import { cleanText } from "./validate";

/** Sign-in works whenever the analysis backend is configured. */
export const isAuthConfigured = isBackendConfigured;

export class AuthNotConnectedError extends Error {
  constructor() {
    super("Sign-in isn’t connected on this site. You were not signed in.");
    this.name = "AuthNotConnectedError";
  }
}

export interface Credentials {
  email: string;
  password: string;
}

export interface Account {
  email: string;
  role: "member" | "admin";
}

function parseAccount(body: unknown): Account {
  const raw = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const email = cleanText(raw.email, 254);
  if (!email) throw new ApiError("The server sent an unexpected sign-in response.", true);
  return { email, role: raw.role === "admin" ? "admin" : "member" };
}

/** Sign in. Resolves with the account; rejects with ApiError ("Email or password is incorrect."). */
export async function signIn(credentials: Credentials): Promise<Account> {
  if (!isAuthConfigured) throw new AuthNotConnectedError();
  const body = await request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });
  return parseAccount(body);
}

export interface SignUpOptions {
  /** Whether this site lets people create their own accounts. */
  open: boolean;
  /** If not empty, only addresses at these domains can sign up. */
  emailDomains: string[];
}

/** What the sign-up page should offer. Assumes closed if the server can't be asked. */
export async function signUpOptions(): Promise<SignUpOptions> {
  if (!isAuthConfigured) return { open: false, emailDomains: [] };
  try {
    const raw = (await request("/auth/options")) as Record<string, unknown> | null;
    const domains = Array.isArray(raw?.emailDomains) ? raw.emailDomains : [];
    return {
      open: raw?.registration === true,
      emailDomains: domains.map((d) => cleanText(d, 190)).filter((d): d is string => Boolean(d)),
    };
  } catch {
    return { open: false, emailDomains: [] };
  }
}

/** Create an account and sign in to it. Rejects with ApiError (e.g. "An account with this email already exists."). */
export async function signUp(credentials: Credentials): Promise<Account> {
  if (!isAuthConfigured) throw new AuthNotConnectedError();
  const body = await request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });
  return parseAccount(body);
}

/** Sign out on the server (ends the session there, not just in this browser). */
export async function signOut(): Promise<void> {
  if (!isAuthConfigured) return;
  await request("/auth/logout", { method: "POST" });
}

/** The signed-in account, or null if not signed in. */
export async function currentAccount(): Promise<Account | null> {
  if (!isAuthConfigured) return null;
  try {
    return parseAccount(await request("/auth/me"));
  } catch {
    return null;
  }
}

/** Only allow returning to a path on this site after sign-in (no open redirects). Parsed the way the
 *  browser will parse it: it drops tabs and newlines and reads a backslash as "/", so "/\t/evil.com" means "//evil.com". */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.length > 300) return "/review";
  const base = "https://rescrub.invalid";
  try {
    const url = new URL(next, base);
    return url.origin === base ? url.pathname + url.search + url.hash : "/review";
  } catch {
    return "/review";
  }
}
