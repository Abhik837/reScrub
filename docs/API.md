# API reference

The API is served under **`/api`** on the website's own origin: `http://localhost:8080/api` locally,
`https://<your domain>/api` when self-hosted.
The website reaches it only through `web/lib/api.ts` and `web/lib/auth.ts`, and the shapes
it accepts are in `web/lib/types.ts` and are validated by `web/lib/validate.ts`.

## Conventions

- All responses are JSON. Errors use an HTTP error status and `{ "error": "Human-readable message" }`.
  The website shows that message.
- **Sign-in:** every `/sessions` request needs the session cookie (`401 {"error":"Please sign in."}`
  otherwise) and only reaches recordings owned by the signed-in account (`404` otherwise,
  the same as for an ID that doesn't exist).
- **Origin:** every `POST`, `PATCH` and `DELETE` must carry `Origin: https://<your domain>`
  (a value in `CORS_ORIGINS`), or it is refused with `403`.
- **IDs:** `sessionId` is a UUID; `eventId` matches `^[A-Za-z0-9_-]{1,128}$`.
- **Rate limits:** uploads 10 per IP per hour and 20 per account per day
  (`UPLOADS_PER_DAY_PER_USER`); 120 requests per minute per IP on session endpoints; sign-in 10
  attempts per email and 60 per IP per 15 minutes; sign-up 10 per IP per hour. Over the limit: `429`.

## Sign-in

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | `{ "email", "password" }` | `{ "email", "role" }` and sets the session cookie. Wrong email or password: `401 {"error":"Email or password is incorrect."}` |
| `GET` | `/auth/options` | – | `{ "registration": true, "emailDomains": [] }`: whether sign-up is open, and to which email domains (empty = any) |
| `POST` | `/auth/register` | `{ "email", "password" }` | `201 { "email", "role": "member" }` and sets the session cookie. `400` invalid email (syntax, the provider's username rules, or a domain that doesn't receive mail) or weak password, `403` sign-up closed or domain not allowed, `409` email already has an account, `429` too many sign-ups from this IP |
| `POST` | `/auth/logout` | – | `{}`. Ends the session on the server and clears the cookie |
| `GET` | `/auth/me` | – | `{ "email", "role" }` (`role` is `member` or `admin`), or `401` |

## Recordings

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `POST` | `/sessions` | `multipart/form-data`: `video` (MP4, ≤ 500 MB, ≤ 60 min, ≤ 4096 px per side, ≤ 120 fps), `name` (≤ 120), `procedureContext` (optional, ≤ 2000), `acknowledged` (`"true"`), `zones` (optional JSON, see below) | `{ "sessionId" }`. Sign-in, origin, `Content-Length` and the upload limits are checked before the video is read: `401`, `403`, `411` (no `Content-Length`), `413` (too large), `429`. Then `415` if it isn't a usable MP4 |
| `GET` | `/sessions` | – | `{ "sessions": [{ "sessionId", "name", "state", "progress", "createdAt" }] }`: your 20 most recent recordings, newest first |
| `GET` | `/sessions/{sessionId}` | – | `JobStatus` |
| `POST` | `/sessions/{sessionId}/cancel` | – | `{}` |
| `PATCH` | `/sessions/{sessionId}/findings/{eventId}` | `{ "reviewStatus": "needs_review" \| "confirmed" \| "dismissed" }` | `{}` |
| `DELETE` | `/sessions/{sessionId}` | – | `{}`. Deletes the recording, labeled video, tracking data and findings |
| `GET` | `/sessions/{sessionId}/annotated.mp4` | – | The labeled video (H.264), with HTTP Range support for seeking. `?download=1` sends it as a file (`rescrub-<session name>-labeled.mp4`) |
| `GET` | `/sessions/{sessionId}/report` | – | `Report`, or 404 if none has been written |
| `POST` | `/sessions/{sessionId}/report` | – | `Report`. Asks Google Gemini to write a final report (see below) |

The website polls `GET /sessions/{id}` every 3 seconds while the job is `queued` or `analyzing`, and
keeps the ID in its address (`/review?session=<id>`) so a refresh reopens the same recording.

### Final report (`Report`)

`POST /sessions/{id}/report` sends **only text** to Google Gemini: each finding's title,
description, reason, evidence labels and times, its uncertainty, the reviewer's decision, summary
counts, the recording length and the optional procedure context. The video, frames, file name,
session name, account details and tracking data are never sent. The report replaces any earlier
one and is deleted with the recording.

Errors: `409` if the analysis isn't finished, `503` if `GEMINI_API_KEY` isn't set (or Gemini is
busy), `502`/`504` if Gemini fails or its answer doesn't pass validation, `429` after
`REPORTS_PER_HOUR_PER_USER` reports in an hour.

```json
{
  "sessionId": "…",
  "generatedAt": "2026-10-18T15:04:05+00:00",
  "model": "gemini-flash-latest",
  "stale": false,
  "stats": { "findings": 3, "confirmed": 1, "needsReview": 1, "dismissed": 1, "highUncertainty": 1 },
  "overview": "Plain-text summary of the session.",
  "keyMoments": [
    { "eventId": "evt-1", "timestampSec": 12.0, "title": "…", "reviewStatus": "confirmed", "uncertainty": "low",
      "summary": "What happened.", "teachingPoint": "What to practice." }
  ],
  "coachingPoints": ["…"],
  "limitations": "What this review can't show."
}
```

Gemini's answer is untrusted: it must match a JSON schema; `keyMoments` may only name existing,
non-dismissed findings; `timestampSec`, `title`, `reviewStatus`, `uncertainty` and `stats` come from
the database, never from the model; all text is plain and length-capped. `stale` is `true` when a
reviewer decision changed after the report was written.

### `JobStatus`

```json
{
  "sessionId": "6f1c…",
  "name": "Suturing lab, station 3",
  "state": "queued | analyzing | completed | failed | canceled",
  "progress": 0.42,
  "queuePosition": 1,
  "error": "only when failed",
  "result": {
    "sessionId": "6f1c…",
    "source": "backend",
    "createdAt": "2026-10-18T18:00:00+00:00",
    "annotatedVideoUrl": "/api/sessions/6f1c…/annotated.mp4",
    "findings": [
      {
        "sessionId": "6f1c…",
        "eventId": "evt-1",
        "timestampSec": 10.5,
        "endSec": 16,
        "title": "Person 2's right hand touches Side table, then Instrument table",
        "objects": ["Side table", "Person 2 right hand", "Instrument table"],
        "description": "What was seen, written neutrally.",
        "reasonForReview": "Why a person should look at this.",
        "evidence": [
          { "label": "Side table", "designation": "nonsterile", "timestampSec": 11, "observation": "…" },
          { "label": "Instrument table", "designation": "sterile", "timestampSec": 15.5, "observation": "…" }
        ],
        "uncertainty": { "level": "low | medium | high", "notes": "Visibility limits." },
        "reviewStatus": "needs_review"
      }
    ]
  }
}
```

- `progress` (0–1) is updated about every 3 seconds while analyzing. `queuePosition`, only while
  `queued`, is how many recordings (anyone's) the worker will analyze before this one.
- `result` is present only when `state` is `completed`. `findings` has at most 200 items and
  each `evidence` list at most 12 steps. All times are seconds from the start of the recording.
- `annotatedVideoUrl` is a path on this origin. The website accepts it only when it is exactly
  `/api/sessions/<sessionId>/annotated.mp4`, and then plays it instead of the local copy.
- `designation` comes from the room's surface configuration: the trained model's classes
  (`backend/config/surfaces_mmor.yaml`) or hand-drawn zones. It is `"unknown"` for anything
  that has no designation. `uncertainty.level` is `high` when contact is judged from image
  position only (no depth).

### Hand-drawn zones (`zones`)

Optional. Used instead of automatic surface detection for that recording; a server-wide
default can be set with `DEFAULT_ZONES_FILE`. Coordinates are pixels or fractions of the
frame, and earlier zones win where they overlap.

```json
[
  {"label": "Sterile drape", "designation": "sterile",
   "polygon": [[0.35, 0.45], [0.65, 0.45], [0.65, 0.8], [0.35, 0.8]]},
  {"label": "Side table", "designation": "nonsterile",
   "polygon": [[0, 0.8], [1, 0.8], [1, 1], [0, 1]]}
]
```

`designation` is one of `sterile`, `nonsterile`, `patient`, `neutral`.

## Tracking data

For analysis tools and models. Same sign-in and ownership rules apply.

| Method | Path | Query | Returns |
| --- | --- | --- | --- |
| `GET` | `/sessions/{id}/people` | – | `Person N` labels, first/last seen, frames, designation (scrubbed = `sterile`) |
| `GET` | `/sessions/{id}/tracks` | `person`, `from`, `to`, `parts` (e.g. `r_wrist,r_index_tip`), `limit` ≤ 50,000 | Keypoints per frame: `video_sec`, `frame`, `person_label`, `part`, `x`, `y`, `conf`, `depth` |
| `GET` | `/sessions/{id}/surfaces` | – | Surface polygons per keyframe, with `designation` |
| `GET` | `/sessions/{id}/proximity` | `candidate_only`, `from`, `to`, `limit` ≤ 50,000 | Hand/arm-to-surface features: `pixel_dist`, `inside_mask`, `depth_gap`, `speed_px_s`, `candidate_contact`, and `person_designation` (the person's role at that frame, as the labeled video shows it) |

## Health

`GET /health` returns `{"ok": true}` when the API can reach the database.
