// Server-only: ask the backend who is signed in, using the browser's cookie.
// API_INTERNAL_URL is the backend's address as seen from this server
// (http://127.0.0.1:8000 on the web server); it is never sent to browsers.
// Imported only from server components (app/review/page.tsx); uses next/headers, so it cannot run in a browser.
import { cookies } from "next/headers";
import type { Account } from "./auth";

const NAMES = ["__Host-rescrub_session", "rescrub_session"];

/** The account, null if not signed in, or "unchecked" if the server can't verify right now. */
export async function serverAccount(): Promise<Account | null | "unchecked"> {
  const internal = process.env.API_INTERNAL_URL;
  if (!internal) return "unchecked";
  const jar = await cookies();
  const name = NAMES.find((n) => jar.has(n));
  if (!name) return null;
  try {
    const res = await fetch(`${internal.replace(/\/$/, "")}/auth/me`, {
      headers: { cookie: `${name}=${jar.get(name)?.value ?? ""}` },
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (res.status === 401) return null;
    if (!res.ok) return "unchecked";
    const body = (await res.json()) as { email?: unknown; role?: unknown };
    return typeof body.email === "string"
      ? { email: body.email.slice(0, 254), role: body.role === "admin" ? "admin" : "member" }
      : "unchecked";
  } catch {
    // Backend unreachable: let the page load; every API call still requires a valid session.
    return "unchecked";
  }
}
