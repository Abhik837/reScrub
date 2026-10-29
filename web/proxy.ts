// Optimistic check only (Next.js guidance): no sign-in cookie → go to /login first.
// The real check happens on the server in app/review/page.tsx and in the backend,
// which verifies the session and ownership on every request.
import { NextResponse, type NextRequest } from "next/server";

export const SESSION_COOKIES = ["__Host-rescrub_session", "rescrub_session"];

export function proxy(request: NextRequest) {
  const { nextUrl } = request;
  // The demonstration is public, and a site without a backend has nothing to protect.
  if (nextUrl.searchParams.get("demo") === "1" || !process.env.NEXT_PUBLIC_API_BASE_URL) return NextResponse.next();
  if (SESSION_COOKIES.some((name) => request.cookies.has(name))) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", nextUrl.pathname + nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = { matcher: ["/review"] };
