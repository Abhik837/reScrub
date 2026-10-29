# Security

How reScrub protects accounts and recordings, on your computer and on self-hosted servers, and how to
check it.

## Accounts and sign-in

| Control | Implementation |
| --- | --- |
| Accounts | Anyone can create a member account with an email and password on **Create account** (`POST /auth/register`), from any email domain, unless `ALLOW_REGISTRATION=false`; `REGISTRATION_EMAIL_DOMAINS` can limit sign-up to listed domains (e.g. `school.edu`). Administrators also create, reset, disable and delete accounts with `python -m rescrub.accounts`; the local stack creates the first admin. Members only ever see their own recordings, and sign-up can't create an admin. There is no email verification, so sign-up reveals whether an address already has an account (`409`), limited to 10 sign-ups per IP per hour. |
| Email checks | `backend/rescrub/emails.py`: ordinary address syntax; for Gmail, Outlook/Hotmail, Yahoo, iCloud, Proton and AOL, that provider's own username rules (length, allowed characters, `+` tags); for any other domain, DNS must show it receives mail (MX, or A/AAAA; a null MX or a missing domain is refused). DNS trouble doesn't block sign-up; `CHECK_EMAIL_DNS=false` turns the lookup off. Without an email service this can't prove the person owns the mailbox. |
| Password storage | Argon2id (`argon2-cffi`), re-hashed automatically when parameters change. Minimum 12 characters, at least 4 different characters, and not mostly the email name; generated passwords are 20 characters. |
| Login errors | One message for every failure ("Email or password is incorrect."). An unknown email takes as long as a wrong password. |
| Brute force and abuse | Sign-in: 10 attempts per email and 60 per IP in 15 minutes. Sign-up: 10 accounts per IP per hour. Uploads: 10 per IP per hour and 20 per account per day (`UPLOADS_PER_DAY_PER_USER`). Then `429`. |
| Session cookie | Random 256-bit value, HttpOnly, SameSite=Lax, Path=/, no Domain, 7 days; only its SHA-256 is stored (`auth_sessions`). Over HTTPS it is `__Host-rescrub_session` and Secure; the local stack uses plain HTTP on `localhost`, so it sets `COOKIE_SECURE=false`. |
| Ending sessions | Sign-out deletes the session on the server. A password reset or disabling an account ends all of that user's sessions immediately. |
| CSRF | SameSite=Lax, plus every POST/PATCH/DELETE must carry an `Origin` listed in `CORS_ORIGINS`. |
| Page protection | `web/proxy.ts` redirects requests without a cookie to `/login`; `web/app/review/page.tsx` checks the session on the server through `API_INTERNAL_URL`; the API checks it again on every request. |
| Return after sign-in | `safeNextPath` parses `?next=` the way the browser will (it drops tabs and newlines and reads `\` as `/`) and keeps it only if it stays on this site. |

## Recordings and data

| Control | Implementation |
| --- | --- |
| Ownership | Every `/sessions/...` request checks that the signed-in account owns the recording; anything else returns `404`, the same as a missing ID. |
| Upload checks | Before the body is read (`check_upload_first` in `api.py`): allowed `Origin`, a valid sign-in, a stated `Content-Length` within the limit, and the upload limits. While streaming: a running size count, plus Caddy's 520 MB limit. Then the MP4 `ftyp` marker and `ffprobe`: a video stream, ≤ 60 min, ≤ 4096 px per side, ≤ 120 frames per second. Text fields: name ≤ 120, context ≤ 2000, acknowledgment required. |
| Storage | Files are named by random UUIDs; the uploaded filename is never used for a path. A Docker volume locally; a private bucket when self-hosted. |
| Retention | The original upload is deleted once the labeled video is made (`DELETE_ORIGINAL_AFTER_PROCESSING=true`). Users delete a recording and everything derived from it with **Delete recording**; administrators can delete an account and all its data. |
| Video delivery | The labeled video is streamed by the API to its owner only. No storage links or static files are ever exposed. The website accepts the video only from `/api/sessions/<id>/annotated.mp4`. |
| Database access | All queries are parameterized. Self-hosted servers connect as `rescrub_app` (`backend/db/app_role.sql`), which can read and write rows but cannot drop or alter tables, over TLS with certificate verification (`sslmode=verify-full`). The local database is reachable only inside Docker. |
| Output limits | ≤ 200 findings per recording, ≤ 12 evidence steps each; timestamps inside the video. |
| Final report (Gemini) | `backend/rescrub/report.py`. Only finding text, reviewer decisions, counts, recording length and the optional procedure context go to Google Gemini; never video, frames, file names, session names, accounts or tracking data. The procedure context is marked as background in the prompt (prompt injection). The answer must match a JSON schema; moments must name existing, non-dismissed findings; numbers and times come from the database; text is plain and length-capped. Owner-only, same-site POST, rate-limited per account (`REPORTS_PER_HOUR_PER_USER`), 60 s timeout. Logs record sizes and timing, never the prompt or the answer. The key lives only in `.env` (local) or `backend/.env` on the web server. |

## Website

| Control | Implementation |
| --- | --- |
| No secrets in browser code | The only public setting is `NEXT_PUBLIC_API_BASE_URL=/api`. The website build ships no source maps. |
| Response validation | `web/lib/validate.ts` checks every API response: known states, safe IDs, timestamps 0–6 h, text length caps, list caps, unknown designations shown as "Unclear", missing uncertainty treated as high. Reports (`parseReport`) are checked the same way, and each moment must match a finding on the page. |
| No HTML from data | All text renders as plain text through React (no `dangerouslySetInnerHTML`). Control and text-direction characters are stripped. |
| Security headers | `web/next.config.ts`: Content-Security-Policy (`default-src 'self'`; scripts, styles, media and connections limited to this site), HSTS, `X-Frame-Options: DENY`, nosniff, Referrer-Policy, Permissions-Policy, Cross-Origin-Opener-Policy. CSP keeps `'unsafe-inline'` for Next.js's inline scripts. |

## Servers (self-hosted)

Locally, only port 8080 on `127.0.0.1` is published; everything else stays inside Docker.


| Control | Implementation |
| --- | --- |
| Network | Web server: only 22, 80 and 443 are open (the API also makes outbound DNS lookups for sign-up email checks); the API (127.0.0.1:8000) and the website (127.0.0.1:3000) are reachable only through Caddy. GPU server: only 22. The worker pulls jobs from the database and needs nothing inbound. |
| HTTPS | Caddy with automatic certificates; `www` redirects to the bare domain. |
| Client addresses | Caddy replaces any client-sent `X-Forwarded-For`, so rate limits can't be bypassed with forged headers. |
| API surface | Interactive API docs are disabled (`ENABLE_API_DOCS=false`); no `Server` header. |
| Processes | The API, worker and website containers run as unprivileged users with every Linux capability dropped and `no-new-privileges`; on the web server the website runs under the `rescrub` user. SSH accepts keys only (no root password login); unattended security upgrades are on. |
| Secrets | `backend/.env` (mode 600) on each server holds `DATABASE_URL`, the storage keys and (web server only) `GEMINI_API_KEY`; `web/.env.local` holds only public or internal addresses. `.gitignore` covers `.env*`, `*credentials*`, `*.pem`, `*.key`. |

## Supply chain

- CI on every pull request (`.github/workflows/ci.yml`): backend lint and tests against Postgres;
  website lint, type check and build; a build and start-up check of the local stack; `npm audit`
  (high severity and above); a gitleaks scan (checksum-verified download) of every commit on every branch.
- The one git dependency (`clip`) is pinned to a commit; everything else comes from PyPI or npm with
  lockfile or minimum-version pins.
- Dependabot opens weekly update PRs for npm, pip, Docker base images and GitHub Actions.

## Security review (October 2026)

A review of the backend, website, containers, Caddy, the self-hosted Vultr + Tiger Cloud setup and the
connections between them. It used code review, `npm audit` and `pip-audit` (no known vulnerabilities),
a secret scan of the tree and history, and tests against a running stack.

**Fixed**

| Finding | Severity | Fix |
| --- | --- | --- |
| Signed-out clients could send a 500 MB upload, which the API wrote to disk before answering `401` (FastAPI reads form bodies before checking sign-in) | Medium | Origin, sign-in, size and limits are checked before the body is read |
| `?next=/%09/evil.com` sent people to another site after sign-in (browsers drop the tab, leaving `//evil.com`) | Medium | `safeNextPath` parses the URL as the browser does |
| Open sign-up would let anyone queue unlimited work on the GPU server | Medium | Per-account daily upload limit; sign-up can be closed or limited to email domains |
| An upload at 1000 frames per second or 8K would occupy the worker for days; a malformed frame rate caused a `500` | Low | Frame rate and resolution limits; invalid rates rejected |
| Tracking reads (`/people`, `/tracks`, `/surfaces`, `/proximity`) weren't rate-limited | Low | Same per-client limit as other reads |
| Login and sign-up fields had no size limit | Low | Bounded |
| The schema set-up command used `sslmode=require` (no certificate check) for the admin login | Low | `verify-full` |
| Containers kept Docker's default Linux capabilities; the GPU server's SSH set-up left root password login to the image default | Low | Capabilities dropped, `no-new-privileges`; `PermitRootLogin prohibit-password`, as on the web server |
| The CLIP dependency followed its default branch; the CI scanner was downloaded without a checksum | Low | Pinned to a commit; checksum verified |

**Accepted, by design**

- **Sign-up reveals whether an email has an account** (`409`): there is no email service for
  verification. Limited to 10 sign-ups per IP per hour; close sign-up or limit it to your domain
  if that matters.
- **Sign-in lockout:** 10 wrong passwords lock an email out for 15 minutes, so someone else can
  delay a person's sign-in. That's the price of stopping password guessing without CAPTCHAs.
- **No self-service password reset** (no email service): an administrator runs `accounts reset`.
- **`'unsafe-inline'` scripts in the CSP:** Next.js needs it without per-request nonces.
- **`--forwarded-allow-ips *` in the API image:** safe only because the API port is never public
  (127.0.0.1 on the web server, the Docker network locally). Don't publish port 8000.
- **Videos are decoded by ffmpeg and OpenCV:** a malicious file targets the worker, which runs
  unprivileged, without capabilities, with no inbound ports, and holds only the database and bucket
  credentials. Keep the worker image updated (Dependabot, `update-worker.sh`).
- **Vultr Object Storage keys reach the whole bucket** (Vultr has no per-prefix keys): both servers
  hold them, so treat either server's compromise as exposure of all recordings, and rotate the keys.
- **Base images are pinned by tag, not digest** (`python:3.14-slim`, `node:24-slim`, `caddy:2`,
  `timescale/timescaledb-ha:pg17`), so they pick up security patches; Dependabot tracks the Dockerfiles; check the compose images (`caddy`, `timescaledb-ha`) when you update.
- **Rate limits are kept in memory** per API process: they reset when the API restarts.

## Verify a deployment

[DEPLOY.md §9](DEPLOY.md#9-verify) has the commands: security headers present, API docs hidden,
requests without sign-in or from other sites refused, ports 3000 and 8000 closed from outside, and
the sign-in rate limit.

## Operating rules

- Never paste passwords, `.env` files, database URLs or private SSH keys into chats, tickets
  or documents. If one is exposed, rotate it immediately ([DEPLOY.md §10](DEPLOY.md#10-operations)).
- Give each person their own account. Disable accounts that are no longer needed:
  `python -m rescrub.accounts disable <email>`.
