"""Analysis worker: claims queued recordings from the database and runs the pipeline and breach rules.

    python -m rescrub.worker

Run one worker per GPU. Several workers can share the database safely.
"""

import json
import logging
import signal
import tempfile
import time
import uuid
from pathlib import Path

from . import db
from .analysis.breaches import analyze_session
from .pipeline.run import Canceled, Models, process_video
from .pipeline.video_io import VideoError, probe
from .settings import get_settings
from .storage import get_storage

log = logging.getLogger("rescrub.worker")
_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True
    log.info("Stopping after the current job")


def default_zones(settings):
    f = settings.default_zones_file
    return json.loads(Path(f).read_text()) if f else None


def run_session(session: dict, pool, storage, models: Models, settings) -> None:
    sid = str(session["id"])
    log.info("Session %s: starting", sid)
    with tempfile.TemporaryDirectory(prefix="rescrub-") as tmp:
        tmp = Path(tmp)
        src = tmp / "input.mp4"
        out = tmp / "annotated.mp4"
        key = None
        try:
            storage.get_file(session["video_key"], src)
            info = probe(src, settings.max_video_sec)
            db.start_session(pool, sid, info)
            recorded_at = db.get_session(pool, sid)["recorded_at"]
            sink = db.DbSink(pool, sid, recorded_at, settings.db_batch_rows)
            last = [0.0]

            def progress(f: float) -> None:
                if f - last[0] >= 0.01:
                    last[0] = f
                    db.update_progress(pool, sid, f)

            process_video(
                src, out, sink, models, settings, zones=session.get("zones") or default_zones(settings), info=info,
                on_progress=progress, should_cancel=lambda: db.is_cancel_requested(pool, sid),
            )
            if settings.run_breach_analysis:
                findings = analyze_session(pool, sid, save=True)
                log.info("Session %s: %d finding(s)", sid, len(findings))
            key = f"annotated/{uuid.uuid4()}.mp4"
            storage.put_file(out, key)
            db.complete_session(pool, sid, key)
            if settings.delete_original_after_processing:
                storage.delete(session["video_key"])
                db.clear_video_key(pool, sid)
            log.info("Session %s: completed", sid)
        except Canceled:
            db.finish_session(pool, sid, "canceled")
            log.info("Session %s: canceled", sid)
        except (VideoError, ValueError) as e:
            db.finish_session(pool, sid, "failed", str(e))
            log.warning("Session %s: rejected: %s", sid, e)
        except Exception:
            log.exception("Session %s: failed", sid)
            db.finish_session(pool, sid, "failed", "Processing failed on the server. Please try again.")
        finally:
            # The owner may delete the recording while it is being analyzed; the job stops at its
            # next cancel check, then everything it wrote after the delete is removed here.
            if db.purge_if_deleted(pool, sid):
                if key:
                    storage.delete(key)
                log.info("Session %s: recording was deleted; removed its remaining data", sid)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    settings = get_settings()
    pool = db.connect(settings.database_url, max_size=3)
    storage = get_storage(settings)
    models = Models.load(settings)
    if n := db.requeue_stale_sessions(pool):
        log.warning("Re-queued %d session(s) left unfinished by a previous worker", n)
    log.info("Worker ready")
    while not _stop:
        session = db.claim_next_session(pool)
        if session is None:
            time.sleep(settings.worker_poll_sec)
            continue
        run_session(session, pool, storage, models, settings)


if __name__ == "__main__":
    main()
