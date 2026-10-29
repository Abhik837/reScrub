# How reScrub works

This page explains every part of reScrub and how the parts connect. For running it, see
[RUN_LOCAL.md](RUN_LOCAL.md) (your computer) or [DEPLOY.md](DEPLOY.md) (your own domain).

## The parts

| Part | Code | Runs as | Talks to |
| --- | --- | --- | --- |
| **Website** | `web/` (Next.js) | `web` container (local) or `next start` under pm2 (server) | the API, through `/api` on the same origin |
| **API** | `backend/rescrub/api.py` (FastAPI) | `api` container | database, storage, Google Gemini, DNS (sign-up email checks) |
| **Worker** | `backend/rescrub/worker.py` + `pipeline/` + `analysis/` | `worker` container: CPU image locally, CUDA image on a GPU | database, storage |
| **Database** | `backend/db/schema.sql` | `db` container (TimescaleDB + pgvector), or Tiger Cloud when self-hosted | — |
| **Storage** | `backend/rescrub/storage.py` | a Docker volume, or an S3-compatible bucket (Vultr Object Storage when self-hosted) | — |
| **Proxy** | `deploy/Caddyfile.local`, `deploy/Caddyfile` | Caddy | routes `/api/*` to the API and the rest to the website |

The website and API share one origin (`http://localhost:8080`, or `https://your-domain.com`), so the
sign-in cookie is first-party and no cross-site requests are needed. The worker has no inbound
port: it pulls jobs from the database. The API and the worker never call each other directly.

## One recording, start to finish

```
Browser                API                       Database                Worker
   │ POST /api/sessions  │ checks sign-in and limits │                       │
   │ (MP4 + name +       │ then size, MP4, length    │                       │
   │  context)           │ saves video to storage ──▶│ sessions: queued      │
   │                     │                           │◀── claim (SKIP LOCKED)│
   │ GET /api/sessions/id│ every 3 s                 │                       │ download video
   │ ◀── queued/analyzing│◀──────── state, progress ─│◀── progress ──────────│ pipeline, frame by frame
   │                     │                           │◀── tracking rows (COPY)
   │                     │                           │◀── findings ──────────│ breach rules
   │                     │                           │◀── completed ─────────│ labeled MP4 → storage
   │ ◀── completed + findings + annotatedVideoUrl    │                       │
   │ GET /api/sessions/id/annotated.mp4 (streamed, seekable, owner only)     │
   │ PATCH …/findings/<id>  Confirm / Dismiss        │                       │
   │ POST  …/report         Gemini writes the report from findings + decisions
```

- The original upload is deleted once the labeled video exists (`DELETE_ORIGINAL_AFTER_PROCESSING`).
- **Cancel** sets a flag that the worker checks between frame batches; **Delete recording** removes
  everything, including data a running job writes afterwards.
- If a worker stops mid-job, the next one re-queues the job when it starts.

Endpoints and response shapes: [API.md](API.md).

## The vision pipeline (worker)

`backend/rescrub/pipeline/run.py` runs these stages on each frame (every `FRAME_STRIDE`th frame):

| # | Stage | Code | Model | Output |
| --- | --- | --- | --- | --- |
| 1 | Detect and track people | `people.py` | YOLO26 pose + BoT-SORT (`config/botsort_reid.yaml`) | boxes, track IDs, shoulder/elbow/wrist/hip keypoints |
| 2 | Stable identities | `identity.py` | YOLO26 classifier as an appearance embedder | `Person N` that survives occlusion; merges tracker IDs by embedding and position |
| 3 | Hands | `hands.py` | RTMW whole-body (ONNX) on each person crop | hand wrist and five fingertips per hand |
| 4 | Surfaces and roles | `surfaces.py` | trained YOLO26-seg (or open-vocabulary YOLOE), every `SURFACE_INTERVAL_SEC` | sterile / non-sterile / patient / neutral polygons with stable IDs; scrubbed vs. unscrubbed votes per person |
| 5 | Depth | `depth.py` | Depth Anything V2 Small, every `DEPTH_INTERVAL_FRAMES` | relative depth at hands and surfaces, to tell hovering from touching |
| 6 | Hand-to-surface features | `proximity.py` | — | for each hand/forearm point within `NEAR_PX` of a surface: distance, inside or not, depth gap, speed, and a `candidate_contact` flag |
| 7 | Labeled video | `render.py` | — | H.264 MP4 with people, skeletons, colored surfaces and a timestamp |

Rows go to the database through `sinks.py` (or to JSON lines with
`python -m rescrub.pipeline.run clip.mp4 --out out/`, no database needed).

**Which models load.** When `SURFACE_CONFIG`, `POSE_MODEL` or `EMBED_MODEL` is not set, the worker
uses the trained file in `backend/models/trained/` if it exists, else the public YOLO26/YOLOE weights
(downloaded on first use). `config/surfaces_mmor.yaml` maps the trained model's classes to
designations; `config/surfaces.yaml` gives the open-vocabulary model its text prompts. A class's
designation can be changed in those files without retraining. Hand-drawn zones (per upload, or
`DEFAULT_ZONES_FILE` for a fixed camera) replace automatic surfaces.

## Breach rules → findings

`backend/rescrub/analysis/breaches.py` groups each person's candidate contacts into events and
applies sterile technique:

| Finding | Rule |
| --- | --- |
| Hand touches *non-sterile*, then *sterile* | a scrubbed person's hand contacts a non-sterile surface, then a sterile one (one chained finding) |
| Hand touches *non-sterile* | a scrubbed hand or forearm contacts a non-sterile surface |
| Unscrubbed person touches *sterile* or *patient* | an unscrubbed person contacts the sterile field, an instrument or the patient |

- Contacts with `neutral` surfaces (the robot) are never findings.
- Event grouping adapts to the frame rate.
- "Scrubbed" or "unscrubbed" is the person's role at the moment of contact, the same one the labeled
  video shows. A person's role is a running vote, so it can change if their label later lands on
  someone else.
- Repeated contacts by one person with the same kind of surface (e.g. the patient) within 30 s
  become one finding, even when the surface's outline gets a new ID at each keyframe.
- Each finding gets an uncertainty and an evidence chain (e.g. side table → hand → instrument table).
- A recording keeps at most 200 findings: the strongest across the whole video, then sorted by time.
- Thresholds live in `Params`; tuned values are read from `models/trained/breach_params.json` when present.
- Re-run on stored data: `python -m rescrub.analysis.breaches --session <id> --save`.

The rules follow the breaches labeled in MM-OR; the mapping and the sterile-field definitions are in
[backend/training/README.md](../backend/training/README.md#what-is-sterile-in-an-or).

## Final report (Gemini)

`backend/rescrub/report.py` sends Gemini only the findings' text, the reviewer's decisions, counts,
the recording length and the optional procedure context; never video, frames, file names or account
data. The answer must match a JSON schema and may only refer to existing findings, and every number
in the report comes from the database. Without `GEMINI_API_KEY`, asking for a report shows "Report
writing isn't set up on this server."; everything else works.

## Database

`backend/db/schema.sql` (applied by `python -m rescrub.init_db`; safe to re-run). TimescaleDB is
optional: without it, the hypertables are plain tables. pgvector is required.

| Table | One row per | Key columns |
| --- | --- | --- |
| `users`, `auth_sessions` | account; signed-in browser | email, Argon2id hash, role, disabled; SHA-256 of the cookie, expiry |
| `sessions` | recording (job) | `owner_id`, `state`, `progress`, `fps`, `width`, `height`, `video_key`, `annotated_key` |
| `people` | person | `person_label`, first/last seen, `designation` (scrubbed = sterile), `mean_embedding` |
| `track_identity` | tracker ID | which tracker IDs were merged into each person |
| `detections` (hypertable) | person × frame | box, confidence |
| `keypoints` (hypertable) | point × person × frame | `part`, `x`, `y`, `conf`, `depth` |
| `surfaces` | surface × keyframe | `label`, `designation`, `polygon` |
| `proximity_events` (hypertable) | point × surface × frame | `pixel_dist`, `inside_mask`, `depth_gap`, `speed_px_s`, `candidate_contact` |
| `findings` | finding | the website's `Finding` JSON and the reviewer's decision |
| `reports` | recording | the latest Gemini report |

`video_sec` is seconds into the recording; `ts` (`recorded_at + video_sec`) partitions the hypertables.

```sql
-- Right index fingertip of Person 2 over time
SELECT video_sec, x, y, depth FROM keypoints
WHERE session_id = $1 AND person_label = 'Person 2' AND part = 'r_index_tip' ORDER BY ts;
```

## Accounts and security

People create their own member accounts with an email and password on **Create account**
(`/register`), from any email domain. `backend/rescrub/emails.py` checks the address: its syntax,
the provider's username rules for Gmail, Outlook, Yahoo, iCloud, Proton and AOL, and for other
domains a DNS lookup showing the domain receives mail. A site can close sign-up
(`ALLOW_REGISTRATION=false`) or limit it to email domains (`REGISTRATION_EMAIL_DOMAINS`).
Administrators manage accounts with `python -m rescrub.accounts add|reset|disable|enable|list|delete`;
the first admin is created by the local stack's `init` service. Sessions are random cookies stored as
hashes; every request is checked for sign-in and ownership, and every write must come from an allowed
origin. Details: [SECURITY.md](SECURITY.md).

## Website

| Path | What it does |
| --- | --- |
| `app/page.tsx` | Home page |
| `app/login/page.tsx`, `components/SignInForm.tsx`, `app/register/page.tsx`, `components/SignUpForm.tsx` | Sign-in and Create account |
| `app/review/page.tsx`, `components/ReviewWorkspace.tsx` | The workspace: set up → upload → analysis → review. **Analyze demo video** uploads the bundled MM-OR clip (`public/demo/mmor-038-demo.mp4`) like any recording; `/review?session=<id>` reopens a recording after a refresh, and **Your recordings** lists recent ones; `/review?demo=1` is a demonstration that needs no backend. |
| `components/VideoPlayer.tsx`, `EventTimeline.tsx`, `FindingsPanel.tsx`, `FindingDetail.tsx`, `ContactChain.tsx` | Labeled video, timeline, findings with Confirm/Dismiss and evidence chains |
| `components/ReportPanel.tsx`, `PrintableReview.tsx` | Gemini report; PDF and JSON export |
| `lib/api.ts`, `lib/auth.ts` | The only code that calls the API |
| `lib/validate.ts`, `lib/types.ts` | Checks every API response against the shapes in [API.md](API.md) |
| `proxy.ts`, `lib/session.ts` | Sends signed-out visitors to `/login`; checks the session on the server |

## Configuration

All backend settings are environment variables, defined with defaults in
`backend/rescrub/settings.py`. The local stack sets them in `docker-compose.local.yml` and reads
optional overrides from the root `.env` ([`.env.example`](../.env.example)); servers read
`backend/.env` ([`backend/.env.example`](../backend/.env.example)). The website reads
`NEXT_PUBLIC_API_BASE_URL` (always `/api`) and `API_INTERNAL_URL` (how its server reaches the API).
