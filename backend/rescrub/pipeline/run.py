"""Labeling + tracking for one recording.

    python -m rescrub.pipeline.run clip.mp4 --out out/ [--zones zones.json] [--db]

Without --db the rows are written as JSON lines in --out; with --db they go to
the database (DATABASE_URL) under a new session.
"""

import argparse
import json
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..settings import Settings, get_settings
from .depth import load_depth_estimator
from .hands import load_hand_estimator
from .identity import IdentityResolver
from .people import PersonTracker
from .proximity import ProximityAnalyzer
from .render import AnnotatedVideoWriter
from .sinks import JsonlSink, Sink
from .surfaces import SurfaceSegmenter, parse_zones
from .video_io import VideoInfo, iter_frames, probe

log = logging.getLogger(__name__)


PROGRESS_EVERY_SEC = 3.0  # how often the website's progress and Cancel are checked
LOG_EVERY_SEC = 60.0


class Canceled(Exception):
    pass


@dataclass
class Models:
    """Loaded once per worker process and reused for every session."""

    tracker: PersonTracker
    surfaces: SurfaceSegmenter
    hands: object | None
    depth: object | None
    device: str

    @classmethod
    def load(cls, settings: Settings) -> "Models":
        device = settings.resolved_device()
        log.info("Loading models on %s: pose %s, identity %s, surfaces %s", device, settings.resolved_pose_model(),
                 settings.resolved_embed_model(), settings.resolved_surface_config().name)

        settings.models_dir.mkdir(parents=True, exist_ok=True)

        def weights(name: str) -> str:
            # Ultralytics downloads its released weights to this path when missing.
            return str(settings.models_dir / name)

        return cls(
            tracker=PersonTracker(weights(settings.resolved_pose_model()), settings.tracker_config, device,
                                  weights(embed) if (embed := settings.resolved_embed_model()) else None),
            surfaces=SurfaceSegmenter(settings.resolved_surface_config(), device, settings.models_dir),
            hands=load_hand_estimator(settings, device),
            depth=load_depth_estimator(settings, device),
            device=device,
        )

    def reset(self) -> None:
        """Fresh tracker and surface-ID state for a new recording."""
        self.tracker.model.predictor = None  # drops BoT-SORT state; rebuilt on the next track() call
        self.surfaces._previous = []
        self.surfaces._counts = {}


def process_video(
    video_path: Path,
    annotated_path: Path,
    sink: Sink,
    models: Models,
    settings: Settings,
    zones=None,
    info: VideoInfo | None = None,
    on_progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> VideoInfo:
    info = info or probe(video_path, settings.max_video_sec)
    models.reset()
    stride = max(1, settings.frame_stride)
    identity = IdentityResolver(
        math.hypot(info.width, info.height),
        settings.reid_similarity,
        settings.reid_max_gap_sec,
        settings.reid_max_speed_frac,
    )
    proximity = ProximityAnalyzer(
        settings.near_px, settings.contact_px, settings.contact_depth_gap, settings.contact_max_speed_px_s
    )
    manual = parse_zones(zones, info.width, info.height) if zones else None
    surfaces = manual or []
    if manual:
        sink.add_surfaces(0.0, manual)
    next_surface_t = 0.0
    depth = None
    writer = AnnotatedVideoWriter(annotated_path, info.width, info.height, info.fps / stride)
    started = time.monotonic()
    expected = max(1, round(info.frame_count / stride))
    next_check = next_log = started  # progress, Cancel and the log line go by time, not frame count
    try:
        for n, (frame_idx, t, frame) in enumerate(iter_frames(video_path, info.fps, stride)):
            roles = []
            if not manual and t >= next_surface_t:
                surfaces = models.surfaces.segment(frame)
                roles = models.surfaces.last_people
                sink.add_surfaces(t, surfaces)
                next_surface_t = t + settings.surface_interval_sec
            if models.depth and n % max(1, settings.depth_interval_frames) == 0:
                depth = models.depth.estimate(frame)

            people = models.tracker.track(frame)
            # Appearance is needed whenever a new tracker ID appears (to merge it
            # with a known person) and periodically to keep each person's profile fresh.
            if n % max(1, settings.embed_interval_frames) == 0:
                models.tracker.embed(frame, people)
            else:
                models.tracker.embed(frame, [p for p in people if p.track_id not in identity.track_to_label])
            identity.assign(people, t)
            if roles:
                identity.apply_roles(people, roles)
            for p in people:
                p.designation = identity.designation(p.person_label)
            if models.hands:
                models.hands.add_hands(frame, people)

            rows, point_depth = proximity.analyze(people, surfaces, t, depth)
            sink.add_frame(frame_idx, t, people, rows, point_depth)
            writer.write(frame, frame_idx, t, people, surfaces, rows)

            now = time.monotonic()
            if now >= next_check:
                next_check = now + PROGRESS_EVERY_SEC
                if should_cancel and should_cancel():
                    raise Canceled()
                if on_progress:
                    on_progress(min(0.99, t / info.duration_sec))
            if now >= next_log:
                next_log = now + LOG_EVERY_SEC
                log.info("progress %d%% (frame %d of ~%d, %.1f s per frame)", min(99, 100 * (n + 1) // expected),
                         n + 1, expected, (now - started) / (n + 1))
        writer.close()
    except BaseException:
        writer.abort()
        raise
    sink.finish(identity)
    log.info(
        "Processed %s: %d people, rows %s, %.1fs",
        video_path.name, len(identity.people), sink.counts, time.monotonic() - started,
    )
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--zones", type=Path, help="JSON file of hand-drawn sterile/nonsterile zones")
    ap.add_argument("--db", action="store_true", help="write to DATABASE_URL instead of JSON lines")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    zones = json.loads(args.zones.read_text()) if args.zones else None
    info = probe(args.video, settings.max_video_sec)
    args.out.mkdir(parents=True, exist_ok=True)
    session_id = str(uuid.uuid4())
    recorded_at = datetime.now(timezone.utc)
    models = Models.load(settings)

    if args.db:
        from .. import db

        pool = db.connect(settings.database_url)
        db.create_session(pool, session_id, name=args.video.name, zones=zones, video_key=None)
        db.start_session(pool, session_id, info)
        sink = db.DbSink(pool, session_id, db.get_session(pool, session_id)["recorded_at"], settings.db_batch_rows)
    else:
        sink = JsonlSink(args.out, session_id, recorded_at, settings.db_batch_rows)

    annotated = args.out / f"{args.video.stem}.annotated.mp4"
    process_video(args.video, annotated, sink, models, settings, zones, info,
                  on_progress=lambda f: log.info("progress %.0f%%", f * 100))
    if args.db:
        db.complete_session(pool, session_id, annotated_key=None)
    print(json.dumps({"session_id": session_id, "annotated_video": str(annotated), "rows": sink.counts}))


if __name__ == "__main__":
    main()
