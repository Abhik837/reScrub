"""Create or update the database schema (db/schema.sql). Safe to re-run.

    python -m rescrub.init_db
"""

import psycopg

from .settings import BACKEND_DIR, get_settings

if __name__ == "__main__":
    sql = (BACKEND_DIR / "db" / "schema.sql").read_text()
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        conn.execute(sql)
        has_ts = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'").fetchone()
    print("Schema ready" + ("" if has_ts else " (TimescaleDB not installed: hypertables skipped)"))
