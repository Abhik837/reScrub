-- Least-privilege login for the reScrub API and worker (instead of tsdbadmin).
-- Run once as tsdbadmin AFTER db/schema.sql, with your own strong password:
--   psql "$ADMIN_DATABASE_URL" -v app_password="'<strong password>'" -f db/app_role.sql
-- Then use this user in DATABASE_URL on both servers.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rescrub_app') THEN
    CREATE ROLE rescrub_app LOGIN;
  END IF;
END $$;
ALTER ROLE rescrub_app PASSWORD :app_password;

DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO rescrub_app', current_database()); END $$;
GRANT USAGE ON SCHEMA public TO rescrub_app;
-- Read/write rows only: no DROP, no ALTER, no new tables.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  sessions, people, track_identity, detections, keypoints, surfaces, proximity_events, findings, reports
  TO rescrub_app;
-- Accounts: the app reads them, records logins, and the accounts CLI creates/updates them.
GRANT SELECT, INSERT, UPDATE, DELETE ON users TO rescrub_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions TO rescrub_app;
