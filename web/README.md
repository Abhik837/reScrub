# reScrub website

Next.js (App Router), TypeScript and Tailwind CSS. Sign-up, sign-in, upload, and the review workspace:
labeled video, timeline, findings with evidence chains, Confirm/Dismiss, the Gemini report, export
and delete. It normally runs as the `web` container of the local stack
([docs/RUN_LOCAL.md](../docs/RUN_LOCAL.md)); how it talks to the API: [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Develop

```bash
npm ci
npm run dev        # http://localhost:3000
npm run lint && npx tsc --noEmit && npm run build
```

Without a backend, the demonstration (`/review?demo=1`) works and the rest of the site says analysis
isn't connected. To connect a backend running on port 8000, see
[docs/RUN_LOCAL.md › Without Docker](../docs/RUN_LOCAL.md#without-docker-for-development).

Settings (`.env.local`, see `.env.example`):

| Variable | Value | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `/api` | Where the browser reaches the API (same origin). Public; baked in at build time. |
| `API_INTERNAL_URL` | `http://api:8000` (local stack), `http://127.0.0.1:8000` (web server) | Server-side only: how the website checks sign-ins before showing `/review`. |
| `API_DEV_PROXY` | `http://127.0.0.1:8000` | `npm run dev` only: forward `/api` to a backend. |

## Where things are

| Path | What it does |
| --- | --- |
| `app/page.tsx` | Homepage (`/`) |
| `app/login/page.tsx`, `components/SignInForm.tsx` | Sign-in (`/login?next=…`) |
| `app/register/page.tsx`, `components/SignUpForm.tsx` | Create account (`/register`); asks `/auth/options` whether sign-up is open |
| `app/review/page.tsx` | Review workspace (`/review`, sign-in required; checks the session on the server). `/review?session=<id>` reopens a recording (set after each upload, so a refresh keeps it); `/review?demo=1` is the public demonstration |
| `proxy.ts` | Sends visitors without a sign-in cookie from `/review` to `/login` |
| `app/terms`, `app/privacy` | Terms and Privacy pages |
| `app/icon.png`, `public/brand/` | Logo and favicon ([docs/ASSETS.md](docs/ASSETS.md)) |
| `components/AppHeader.tsx`, `AccountNav.tsx` | Header with the signed-in account and Sign out |
| `components/ReviewWorkspace.tsx` | Workspace state: setup → upload → analysis → review |
| `components/VideoUpload.tsx` | Drag-and-drop / file picker, preview, replace/remove |
| `components/SessionSetup.tsx`, `SetupStep.tsx` | Numbered steps: recording, context, permission, analyze |
| `components/AnalysisStatus.tsx` | Uploading / queued (place in queue) / analyzing (percentage) / failed / canceled panel |
| `components/RecentRecordings.tsx` | **Your recordings**: recent recordings from `GET /sessions`, to reopen or cancel |
| `components/VideoPlayer.tsx` | Player with keyboard controls; plays the labeled video when available |
| `components/EventTimeline.tsx` | Scrubber with numbered finding markers |
| `components/FindingsPanel.tsx`, `FindingDetail.tsx` | Filters, finding cards, Confirm/Dismiss/Undo |
| `components/ContactChain.tsx` | Evidence chain (e.g. side table → hand → instrument table) |
| `components/ReviewSummary.tsx` | Session summary, Export review, Delete recording |
| `lib/api.ts` | The only module that calls the analysis API |
| `lib/auth.ts`, `lib/session.ts` | Sign-in, sign-out, current account (browser); session check (server) |
| `lib/validate.ts` | Validation of every API response |
| `lib/types.ts` | Data shapes shared with the API ([docs/API.md](../docs/API.md)) |
| `lib/demo.ts`, `scripts/make_demo_video.py` | Demonstration findings and the synthetic clip they describe; the path and session details of the MM-OR clip that **Analyze demo video** uploads (`public/demo/`, [notice](public/demo/README.md)) |

## Rules

- Demo findings are only shown with the synthetic demo clip, never on an uploaded video.
- No secrets in this folder: `NEXT_PUBLIC_API_BASE_URL` is public and `API_INTERNAL_URL` is an
  internal address.
- Checks in the browser are conveniences; the API enforces every rule ([docs/SECURITY.md](../docs/SECURITY.md)).

## Troubleshooting

**Styles look out of date after editing `app/globals.css`.** Stop the dev server, delete
`.next/cache/turbopack`, and start it again.
