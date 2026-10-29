import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def tiny_mp4(tmp_path) -> Path:
    """A 2-second 320x240 H.264 MP4 made with ffmpeg's test source."""
    path = tmp_path / "tiny.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


@pytest.fixture
def pool():
    """Connection pool to a disposable database with db/schema.sql applied.

    Set TEST_DATABASE_URL (e.g. postgresql://rescrub:rescrub@localhost/rescrub_test) to run DB tests.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    from rescrub import db

    schema = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", url, "-f", str(schema)], check=True,
                   capture_output=True)
    p = db.connect(url)
    with p.connection() as c:
        c.execute("TRUNCATE users, auth_sessions, sessions, detections, keypoints, proximity_events CASCADE")
    yield p
    p.close()
