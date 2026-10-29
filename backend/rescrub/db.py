"""Database access (PostgreSQL with TimescaleDB + pgvector): accounts, the job queue, tracking rows, findings."""

from datetime import datetime

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from .pipeline.identity import IdentityResolver
from .pipeline.sinks import JsonlSink, Sink, people_summary
from .pipeline.surfaces import Surface
from .pipeline.video_io import VideoInfo


def connect(database_url: str, max_size: int = 5, wait_sec: float = 60) -> ConnectionPool:
    pool = ConnectionPool(
        database_url,
        min_size=1,
        max_size=max_size,
        # A connection attempt that hangs (no answer at all) is abandoned after 10 s and retried.
        kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 10},
        configure=register_vector,
        open=True,
    )
    try:
        pool.wait(timeout=wait_sec)
    except PoolTimeout:
        pool.close()
        problem = _connect_problem(database_url)
        raise RuntimeError(f"Can't use the database at {_where(database_url)}: {problem}") from None
    return pool


def _where(database_url: str) -> str:
    """host:port/dbname from the URL, without the user or password."""
    info = conninfo_to_dict(database_url)
    return f"{info.get('host', 'localhost')}:{info.get('port', 5432)}/{info.get('dbname', '')}"


def _connect_problem(database_url: str) -> str:
    """The pool retries quietly and only reports a timeout; one direct attempt shows the real cause."""
    try:
        with psycopg.connect(database_url, connect_timeout=10) as conn:
            register_vector(conn)
    except Exception as e:  # noqa: BLE001 - any error is the answer we are looking for
        return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return "it answered only now; it was probably still starting (try again)"


# --- sessions / job queue ---------------------------------------------------

def create_session(pool, session_id: str, *, name: str = "", procedure_context: str = "",
                   designated_objects: str = "", zones=None, video_key: str | None, owner_id=None) -> None:
    with pool.connection() as c:
        c.execute(
            """INSERT INTO sessions (id, name, procedure_context, designated_objects, zones, video_key, owner_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (session_id, name, procedure_context, designated_objects,
             Jsonb(zones) if zones is not None else None, video_key, owner_id),
        )


def get_session(pool, session_id: str) -> dict | None:
    with pool.connection() as c:
        return c.execute("SELECT * FROM sessions WHERE id = %s", (session_id,)).fetchone()


def claim_next_session(pool) -> dict | None:
    """Atomically take the oldest queued session (safe with several workers)."""
    with pool.connection() as c:
        return c.execute(
            """UPDATE sessions SET state = 'analyzing', progress = 0, updated_at = now()
               WHERE id = (SELECT id FROM sessions WHERE state = 'queued' AND NOT cancel_requested
                           ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
               RETURNING *"""
        ).fetchone()


def requeue_stale_sessions(pool, minutes: int = 15) -> int:
    """Put back sessions whose worker died mid-run (no progress update for `minutes`)."""
    with pool.connection() as c:
        cur = c.execute(
            """UPDATE sessions SET state = 'queued', updated_at = now()
               WHERE state = 'analyzing' AND updated_at < now() - make_interval(mins => %s)""",
            (minutes,),
        )
        return cur.rowcount


def start_session(pool, session_id: str, info: VideoInfo) -> None:
    """Record video metadata and clear rows from any earlier run of this session."""
    with pool.connection() as c, c.transaction():
        for table in ("detections", "keypoints", "proximity_events", "surfaces", "people", "track_identity"):
            c.execute(f"DELETE FROM {table} WHERE session_id = %s", (session_id,))
        c.execute(
            """UPDATE sessions SET state = 'analyzing', fps = %s, width = %s, height = %s, duration_sec = %s,
                      frame_count = %s, updated_at = now() WHERE id = %s""",
            (info.fps, info.width, info.height, info.duration_sec, info.frame_count, session_id),
        )


def update_progress(pool, session_id: str, fraction: float) -> None:
    with pool.connection() as c:
        c.execute("UPDATE sessions SET progress = %s, updated_at = now() WHERE id = %s", (fraction, session_id))


def is_cancel_requested(pool, session_id: str) -> bool:
    with pool.connection() as c:
        row = c.execute("SELECT cancel_requested FROM sessions WHERE id = %s", (session_id,)).fetchone()
        return row is None or bool(row["cancel_requested"])  # a deleted recording counts as canceled


def complete_session(pool, session_id: str, annotated_key: str | None) -> None:
    with pool.connection() as c:
        c.execute(
            """UPDATE sessions SET state = 'completed', progress = 1, annotated_key = %s, error = NULL,
                      updated_at = now() WHERE id = %s""",
            (annotated_key, session_id),
        )


def finish_session(pool, session_id: str, state: str, error: str | None = None) -> None:
    """Mark a session failed or canceled."""
    with pool.connection() as c:
        c.execute(
            "UPDATE sessions SET state = %s, error = %s, updated_at = now() WHERE id = %s",
            (state, error, session_id),
        )


def request_cancel(pool, session_id: str) -> str | None:
    """Queued sessions cancel immediately; running ones stop at the worker's next check."""
    with pool.connection() as c:
        row = c.execute(
            """UPDATE sessions SET cancel_requested = true,
                      state = CASE WHEN state = 'queued' THEN 'canceled' ELSE state END,
                      updated_at = now()
               WHERE id = %s RETURNING state""",
            (session_id,),
        ).fetchone()
        return row["state"] if row else None


def delete_session(pool, session_id: str) -> list[str]:
    """Delete a recording's rows everywhere; returns its storage keys for the caller to delete."""
    with pool.connection() as c, c.transaction():
        row = c.execute("SELECT video_key, annotated_key FROM sessions WHERE id = %s", (session_id,)).fetchone()
        if row is None:
            return []
        _delete_tracking_rows(c, session_id)
        c.execute("DELETE FROM sessions WHERE id = %s", (session_id,))  # cascades to the rest
    return [k for k in (row["video_key"], row["annotated_key"]) if k]


def _delete_tracking_rows(c, session_id: str) -> None:
    # Time-series tables have no foreign key (hypertables), so delete them explicitly.
    for table in ("detections", "keypoints", "proximity_events"):
        c.execute(f"DELETE FROM {table} WHERE session_id = %s", (session_id,))


def purge_if_deleted(pool, session_id: str) -> bool:
    """After a job ends: if its recording was deleted meanwhile, remove rows the job wrote since."""
    with pool.connection() as c, c.transaction():
        if c.execute("SELECT 1 FROM sessions WHERE id = %s", (session_id,)).fetchone():
            return False
        _delete_tracking_rows(c, session_id)
    return True


def uploads_since(pool, owner_id, hours: float) -> int:
    with pool.connection() as c:
        return c.execute(
            "SELECT count(*) AS n FROM sessions WHERE owner_id = %s AND created_at > now() - %s * interval '1 hour'",
            (owner_id, hours),
        ).fetchone()["n"]


def list_sessions(pool, owner_id, limit: int = 20) -> list[dict]:
    """The owner's most recent recordings, newest first."""
    with pool.connection() as c:
        return c.execute(
            """SELECT id, name, state, progress, created_at FROM sessions
               WHERE owner_id = %s ORDER BY created_at DESC LIMIT %s""",
            (owner_id, limit),
        ).fetchall()


def queue_position(pool, session: dict) -> int:
    """How many recordings (anyone's) the worker takes before this queued one."""
    with pool.connection() as c:
        return c.execute(
            """SELECT count(*) AS n FROM sessions
               WHERE (state = 'analyzing' OR (state = 'queued' AND NOT cancel_requested)) AND created_at < %s""",
            (session["created_at"],),
        ).fetchone()["n"]


def session_ids_for_owner(pool, owner_id) -> list[str]:
    with pool.connection() as c:
        return [str(r["id"]) for r in c.execute("SELECT id FROM sessions WHERE owner_id = %s", (owner_id,))]


def clear_video_key(pool, session_id: str) -> None:
    with pool.connection() as c:
        c.execute("UPDATE sessions SET video_key = NULL WHERE id = %s", (session_id,))


# --- findings (written by the breach analysis) --------------------------------

def list_findings(pool, session_id: str) -> list[dict]:
    with pool.connection() as c:
        rows = c.execute(
            "SELECT payload, review_status FROM findings WHERE session_id = %s ORDER BY timestamp_sec, event_id",
            (session_id,),
        ).fetchall()
    return [{**r["payload"], "sessionId": session_id, "reviewStatus": r["review_status"]} for r in rows]


def upsert_finding(pool, session_id: str, finding: dict) -> None:
    with pool.connection() as c:
        c.execute(
            """INSERT INTO findings (session_id, event_id, timestamp_sec, payload, review_status)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (session_id, event_id) DO UPDATE
               SET timestamp_sec = EXCLUDED.timestamp_sec, payload = EXCLUDED.payload, updated_at = now()""",
            (session_id, finding["eventId"], finding["timestampSec"], Jsonb(finding),
             finding.get("reviewStatus", "needs_review")),
        )


def replace_findings(pool, session_id: str, findings: list[dict]) -> None:
    """Swap in a fresh analysis result (e.g. after re-processing a recording)."""
    with pool.connection() as c, c.transaction():
        c.execute("DELETE FROM findings WHERE session_id = %s", (session_id,))
        c.cursor().executemany(
            """INSERT INTO findings (session_id, event_id, timestamp_sec, payload, review_status)
               VALUES (%s, %s, %s, %s, %s)""",
            [(session_id, f["eventId"], f["timestampSec"], Jsonb(f), f.get("reviewStatus", "needs_review"))
             for f in findings],
        )


def set_review_status(pool, session_id: str, event_id: str, status: str) -> bool:
    with pool.connection() as c:
        cur = c.execute(
            """UPDATE findings SET review_status = %s, updated_at = now()
               WHERE session_id = %s AND event_id = %s""",
            (status, session_id, event_id),
        )
        return cur.rowcount > 0


def get_report(pool, session_id: str) -> dict | None:
    """The saved Gemini report (rescrub/report.py) or None."""
    with pool.connection() as c:
        row = c.execute("SELECT payload FROM reports WHERE session_id = %s", (session_id,)).fetchone()
    return row["payload"] if row else None


def save_report(pool, session_id: str, report: dict) -> None:
    """Replace the session's report with a newly written one."""
    with pool.connection() as c:
        c.execute(
            """INSERT INTO reports (session_id, model, decisions_hash, payload) VALUES (%s, %s, %s, %s)
               ON CONFLICT (session_id) DO UPDATE SET model = EXCLUDED.model,
                 decisions_hash = EXCLUDED.decisions_hash, payload = EXCLUDED.payload, created_at = now()""",
            (session_id, report["model"], report["decisionsHash"], Jsonb(report)),
        )


# --- tracking data reads (for the analysis instance / model) ----------------

def list_people(pool, session_id: str) -> list[dict]:
    with pool.connection() as c:
        return c.execute(
            """SELECT person_label, first_seen_sec, last_seen_sec, frames_seen, designation
               FROM people WHERE session_id = %s
               ORDER BY first_seen_sec, person_label""",
            (session_id,),
        ).fetchall()


def list_keypoints(pool, session_id: str, person: str | None, start: float | None, end: float | None,
                   parts: list[str] | None, limit: int) -> list[dict]:
    q = ["SELECT video_sec, frame, person_label, part, x, y, conf, depth FROM keypoints WHERE session_id = %s"]
    args: list = [session_id]
    if person:
        q.append("AND person_label = %s")
        args.append(person)
    if start is not None:
        q.append("AND video_sec >= %s")
        args.append(start)
    if end is not None:
        q.append("AND video_sec <= %s")
        args.append(end)
    if parts:
        q.append("AND part = ANY(%s)")
        args.append(parts)
    q.append("ORDER BY ts, person_label, part LIMIT %s")
    args.append(limit)
    with pool.connection() as c:
        return c.execute(" ".join(q), args).fetchall()


def list_surfaces(pool, session_id: str) -> list[dict]:
    with pool.connection() as c:
        return c.execute(
            """SELECT keyframe_sec, surface_id, label, designation, source, conf, area_px, polygon
               FROM surfaces WHERE session_id = %s ORDER BY keyframe_sec, surface_id""",
            (session_id,),
        ).fetchall()


def list_proximity(pool, session_id: str, candidate_only: bool, start: float | None, end: float | None,
                   limit: int) -> list[dict]:
    q = ["""SELECT video_sec, frame, person_label, part, surface_id, designation, pixel_dist, inside_mask,
                   depth_gap, speed_px_s, candidate_contact, person_designation
            FROM proximity_events WHERE session_id = %s"""]
    args: list = [session_id]
    if candidate_only:
        q.append("AND candidate_contact")
    if start is not None:
        q.append("AND video_sec >= %s")
        args.append(start)
    if end is not None:
        q.append("AND video_sec <= %s")
        args.append(end)
    q.append("ORDER BY ts, person_label, part LIMIT %s")
    args.append(limit)
    with pool.connection() as c:
        return c.execute(" ".join(q), args).fetchall()


# --- pipeline sink ----------------------------------------------------------

class DbSink(Sink):
    """Streams tracking rows into the database with COPY."""

    def __init__(self, pool, session_id: str, recorded_at: datetime, batch_rows: int = 5000):
        super().__init__(session_id, recorded_at, batch_rows)
        self.pool = pool

    def write_rows(self, table: str, rows: list[tuple]) -> None:
        cols = ", ".join(JsonlSink.COLUMNS[table])
        with self.pool.connection() as c, c.transaction():
            with c.cursor().copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)

    def add_surfaces(self, keyframe_sec: float, surfaces: list[Surface]) -> None:
        if not surfaces:
            return
        with self.pool.connection() as c, c.transaction():
            c.cursor().executemany(
                """INSERT INTO surfaces (session_id, keyframe_sec, surface_id, label, designation, source, conf,
                                         polygon, area_px)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                [(self.session_id, keyframe_sec, s.surface_id, s.label, s.designation, s.source, s.conf,
                  Jsonb(s.polygon), s.area) for s in surfaces],
            )

    def finish(self, identity: IdentityResolver) -> None:
        self.flush()
        people = people_summary(identity)
        with self.pool.connection() as c, c.transaction():
            cur = c.cursor()
            cur.executemany(
                """INSERT INTO people (session_id, person_label, first_seen_sec, last_seen_sec, frames_seen,
                                       designation, mean_embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                [(self.session_id, p["person_label"], p["first_seen_sec"], p["last_seen_sec"], p["frames_seen"],
                  p["designation"],
                  np.asarray(p["mean_embedding"], np.float32) if p["mean_embedding"] is not None else None)
                 for p in people],
            )
            cur.executemany(
                "INSERT INTO track_identity (session_id, track_id, person_label, first_seen_sec) "
                "VALUES (%s, %s, %s, %s)",
                [(self.session_id, tid, label, identity.track_first_seen[tid])
                 for tid, label in identity.track_to_label.items()],
            )
