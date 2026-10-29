import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

/** The backend's origin if it is on another host (absolute URL). Normally it is "/api" on this origin, so nothing extra is needed. */
function apiOrigin(): string {
  try {
    return process.env.NEXT_PUBLIC_API_BASE_URL ? new URL(process.env.NEXT_PUBLIC_API_BASE_URL).origin : "";
  } catch {
    return "";
  }
}

// Content-Security-Policy: what this site's pages may load or connect to.
// - scripts/styles: only this site. 'unsafe-inline' is needed because Next.js adds
//   small inline scripts; removing it requires nonces (dynamic rendering).
// - images: this site (next/image proxies the Unsplash photo through /_next/image).
// - media: this site (demo clip), blob: (local preview of the chosen video) and the
//   analysis backend (the labeled video it streams for a finished session).
// - connect: this site and the analysis backend only.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `media-src 'self' blob: ${apiOrigin()}`.trim(),
  `connect-src 'self' ${apiOrigin()}${isDev ? " ws: wss:" : ""}`.trim(),
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()" },
  // Only takes effect over HTTPS. No "preload": that's a hard-to-undo commitment.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // `npm run dev` only: forward /api to a backend (otherwise Caddy does this).
  async rewrites() {
    const target = process.env.API_DEV_PROXY;
    return target ? [{ source: "/api/:path*", destination: `${target.replace(/\/$/, "")}/:path*` }] : [];
  },
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
  images: {
    // Homepage photo, served from Unsplash's CDN (see docs/ASSETS.md for credit and license).
    remotePatterns: [new URL("https://images.unsplash.com/photo-1728102199887-a285f8957c5d")],
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
