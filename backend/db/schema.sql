-- reScrub schema: PostgreSQL with pgvector, and TimescaleDB when available (the local `db`
-- container and Tiger Cloud both have it).
--
-- Apply with `python -m rescrub.init_db` or `psql "$DATABASE_URL" -f db/schema.sql`.
-- Safe to re-run. Without TimescaleDB the time-series tables stay ordinary tables.
--
-- Time: every time-series row has `ts` (wall clock = sessions.recorded_at +
-- video_sec) for TimescaleDB partitioning, and `video_sec` (seconds from the
-- start of the recording), which is what the website and analysis use.

CREATE EXTENSION IF NOT EXISTS vector;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
  END IF;
END $$;

-- Accounts: created on the sign-up page (POST /auth/register) or with `python -m rescrub.accounts`. Emails are stored lower-case.
CREATE TABLE IF NOT EXISTS users (
  id                  uuid PRIMARY KEY,
  email               text NOT NULL UNIQUE CHECK (email = lower(email)),
  password_hash       text NOT NULL,                -- Argon2id
  role                text NOT NULL DEFAULT 'member' CHECK (role IN ('member','admin')),
  disabled            boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  password_changed_at timestamptz NOT NULL DEFAULT now(),
  last_login_at       timestamptz
);

-- Signed-in browsers. Only a SHA-256 of the cookie value is stored.
CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash   bytea PRIMARY KEY,
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_sessions_user_idx ON auth_sessions (user_id);

-- One uploaded recording and its processing job.
CREATE TABLE IF NOT EXISTS sessions (
  id                 uuid PRIMARY KEY,
  name               text NOT NULL DEFAULT '',
  procedure_context  text NOT NULL DEFAULT '',
  designated_objects text NOT NULL DEFAULT '',
  zones              jsonb,                       -- optional hand-drawn sterile/nonsterile polygons
  state              text NOT NULL DEFAULT 'queued'
                     CHECK (state IN ('queued','analyzing','completed','failed','canceled')),
  progress           real NOT NULL DEFAULT 0,     -- 0..1 while analyzing
  error              text,
  cancel_requested   boolean NOT NULL DEFAULT false,
  video_key          text,                        -- object-storage key of the original upload
  annotated_key      text,                        -- object-storage key of the labeled H.264 video
  fps                double precision,
  width              integer,
  height             integer,
  duration_sec       double precision,
  frame_count        integer,
  recorded_at        timestamptz NOT NULL DEFAULT now(),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_state_idx ON sessions (state, created_at);
-- Who uploaded it. Every API request checks it; rows from before sign-in existed have no owner
-- and are not reachable through the API.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS sessions_owner_idx ON sessions (owner_id, created_at);

-- Anonymous people: "Person 1", "Person 2", ... stable for the whole recording.
CREATE TABLE IF NOT EXISTS people (
  session_id      uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  person_label    text NOT NULL,
  first_seen_sec  double precision NOT NULL,
  last_seen_sec   double precision NOT NULL,
  frames_seen     integer NOT NULL DEFAULT 0,
  designation     text NOT NULL DEFAULT 'sterile',  -- scrubbed (sterile) unless the OR role model saw them unscrubbed
  mean_embedding  vector,                           -- appearance (ReID) embedding
  PRIMARY KEY (session_id, person_label)
);

-- Which tracker IDs were merged into which person.
CREATE TABLE IF NOT EXISTS track_identity (
  session_id   uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  track_id     integer NOT NULL,
  person_label text NOT NULL,
  first_seen_sec double precision NOT NULL,
  PRIMARY KEY (session_id, track_id)
);

-- Per-frame person boxes.
CREATE TABLE IF NOT EXISTS detections (
  ts           timestamptz NOT NULL,
  session_id   uuid NOT NULL,
  video_sec    double precision NOT NULL,
  frame        integer NOT NULL,
  person_label text NOT NULL,
  track_id     integer NOT NULL,
  x1 real NOT NULL, y1 real NOT NULL, x2 real NOT NULL, y2 real NOT NULL,
  conf         real NOT NULL
);
CREATE INDEX IF NOT EXISTS detections_session_idx ON detections (session_id, person_label, ts);

-- Per-frame body and hand points (pixels in the original frame).
-- part: l_shoulder, r_shoulder, l_elbow, r_elbow, l_wrist, r_wrist, l_hip, r_hip
--       and hand points l_hand_wrist, l_thumb_tip, l_index_tip, l_middle_tip,
--       l_ring_tip, l_pinky_tip (same with r_).
CREATE TABLE IF NOT EXISTS keypoints (
  ts           timestamptz NOT NULL,
  session_id   uuid NOT NULL,
  video_sec    double precision NOT NULL,
  frame        integer NOT NULL,
  person_label text NOT NULL,
  part         text NOT NULL,
  x real NOT NULL, y real NOT NULL,
  conf         real NOT NULL,
  depth        real                -- relative depth (Depth Anything V2), larger = closer
);
CREATE INDEX IF NOT EXISTS keypoints_session_idx ON keypoints (session_id, person_label, part, ts);

-- Sterile / nonsterile surfaces, one row per surface per keyframe.
CREATE TABLE IF NOT EXISTS surfaces (
  session_id    uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  keyframe_sec  double precision NOT NULL,
  surface_id    text NOT NULL,      -- stable across keyframes, e.g. "sterile-drape-1"
  label         text NOT NULL,
  designation   text NOT NULL,      -- sterile | nonsterile | patient | neutral (constraint below)
  source        text NOT NULL CHECK (source IN ('auto','manual')),
  conf          real,
  polygon       jsonb NOT NULL,     -- [[x, y], ...] in pixels
  area_px       integer NOT NULL,
  PRIMARY KEY (session_id, keyframe_sec, surface_id)
);

-- Re-runnable: older databases only allowed sterile/nonsterile.
ALTER TABLE surfaces DROP CONSTRAINT IF EXISTS surfaces_designation_check;
ALTER TABLE surfaces ADD CONSTRAINT surfaces_designation_check
  CHECK (designation IN ('sterile','nonsterile','patient','neutral'));

-- Hand/arm point near a surface. These are features for the contamination
-- model, not verdicts. candidate_contact is a simple heuristic flag.
CREATE TABLE IF NOT EXISTS proximity_events (
  ts           timestamptz NOT NULL,
  session_id   uuid NOT NULL,
  video_sec    double precision NOT NULL,
  frame        integer NOT NULL,
  person_label text NOT NULL,
  part         text NOT NULL,
  surface_id   text NOT NULL,
  designation  text NOT NULL,
  pixel_dist   real NOT NULL,       -- 0 when the point is inside the surface mask
  inside_mask  boolean NOT NULL,
  depth_gap    real,                -- point depth minus surface depth near the point
  speed_px_s   real,
  candidate_contact boolean NOT NULL
);
CREATE INDEX IF NOT EXISTS proximity_session_idx ON proximity_events (session_id, ts);
-- The person's role (sterile = scrubbed) at that frame, as drawn in the labeled video. Older rows: NULL.
ALTER TABLE proximity_events ADD COLUMN IF NOT EXISTS person_designation text;

-- Findings shown on the website, written by the breach analysis; payload is a Finding
-- exactly as in web/lib/types.ts.
CREATE TABLE IF NOT EXISTS findings (
  session_id    uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  event_id      text NOT NULL,
  timestamp_sec double precision NOT NULL,
  payload       jsonb NOT NULL,
  review_status text NOT NULL DEFAULT 'needs_review'
                CHECK (review_status IN ('needs_review','confirmed','dismissed')),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, event_id)
);

-- The latest final review report written by Gemini for a recording (rescrub/report.py).
-- decisions_hash records the reviewer decisions it was written from, so the website can say
-- when a report is out of date.
CREATE TABLE IF NOT EXISTS reports (
  session_id     uuid PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  model          text NOT NULL,
  decisions_hash text NOT NULL,
  payload        jsonb NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- Turn the time-series tables into compressed hypertables on TimescaleDB.
DO $$
DECLARE t text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    RAISE NOTICE 'timescaledb not installed: time-series tables stay plain tables';
    RETURN;
  END IF;
  FOREACH t IN ARRAY ARRAY['detections','keypoints','proximity_events'] LOOP
    PERFORM create_hypertable(t, by_range('ts', INTERVAL '1 day'), if_not_exists => true);
    CONTINUE WHEN EXISTS (
      SELECT 1 FROM timescaledb_information.hypertables
      WHERE hypertable_name = t AND compression_enabled);
    EXECUTE format(
      'ALTER TABLE %I SET (timescaledb.compress, timescaledb.compress_segmentby = %L, timescaledb.compress_orderby = %L)',
      t, 'session_id', 'ts');
    PERFORM add_compression_policy(t, INTERVAL '7 days', if_not_exists => true);
  END LOOP;
END $$;
