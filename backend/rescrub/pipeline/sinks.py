"""Where pipeline output goes. DbSink (rescrub.db) writes to the database;
JsonlSink writes files for running the pipeline without a database."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from .identity import IdentityResolver
from .people import PersonObs
from .proximity import ProximityRow
from .surfaces import Surface


class Sink:
    """Collects rows in memory and calls `write_rows` in batches."""

    TABLES = ("detections", "keypoints", "proximity_events")

    def __init__(self, session_id: str, recorded_at: datetime, batch_rows: int = 5000):
        self.session_id = session_id
        self.recorded_at = recorded_at
        self.batch_rows = batch_rows
        self.buffers: dict[str, list[tuple]] = {t: [] for t in self.TABLES}
        self.counts: dict[str, int] = {t: 0 for t in self.TABLES}

    def add_frame(
        self,
        frame_idx: int,
        t: float,
        people: list[PersonObs],
        rows: list[ProximityRow],
        point_depth: dict[tuple[str, str], float],
    ) -> None:
        ts = self.recorded_at + timedelta(seconds=t)
        sid = self.session_id
        for p in people:
            self.buffers["detections"].append(
                (ts, sid, t, frame_idx, p.person_label, p.track_id, *p.box, p.conf)
            )
            for part, (x, y, c) in p.points.items():
                self.buffers["keypoints"].append(
                    (ts, sid, t, frame_idx, p.person_label, part, x, y, c, point_depth.get((p.person_label, part)))
                )
        for r in rows:
            self.buffers["proximity_events"].append(
                (ts, sid, t, frame_idx, r.person_label, r.part, r.surface_id, r.designation, r.pixel_dist,
                 r.inside_mask, r.depth_gap, r.speed_px_s, r.candidate_contact, r.person_designation)
            )
        if sum(len(b) for b in self.buffers.values()) >= self.batch_rows:
            self.flush()

    def flush(self) -> None:
        for table, rows in self.buffers.items():
            if rows:
                self.write_rows(table, rows)
                self.counts[table] += len(rows)
                self.buffers[table] = []

    def add_surfaces(self, keyframe_sec: float, surfaces: list[Surface]) -> None:
        raise NotImplementedError

    def finish(self, identity: IdentityResolver) -> None:
        raise NotImplementedError

    def write_rows(self, table: str, rows: list[tuple]) -> None:
        raise NotImplementedError


def people_summary(identity: IdentityResolver) -> list[dict]:
    return [
        {
            "person_label": p.label,
            "first_seen_sec": p.first_seen,
            "last_seen_sec": p.last_seen,
            "frames_seen": p.frames_seen,
            "designation": p.designation,
            "mean_embedding": p.mean_embedding,
        }
        for p in identity.people.values()
    ]


class JsonlSink(Sink):
    """One JSON-lines file per table in `out_dir`."""

    COLUMNS = {
        "detections": ["ts", "session_id", "video_sec", "frame", "person_label", "track_id", "x1", "y1", "x2", "y2",
                       "conf"],
        "keypoints": ["ts", "session_id", "video_sec", "frame", "person_label", "part", "x", "y", "conf", "depth"],
        "proximity_events": ["ts", "session_id", "video_sec", "frame", "person_label", "part", "surface_id",
                             "designation", "pixel_dist", "inside_mask", "depth_gap", "speed_px_s",
                             "candidate_contact", "person_designation"],
    }

    def __init__(self, out_dir: Path, session_id: str, recorded_at: datetime, batch_rows: int = 5000):
        super().__init__(session_id, recorded_at, batch_rows)
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for t in (*self.TABLES, "surfaces"):
            (self.out_dir / f"{t}.jsonl").write_text("")

    def _append(self, name: str, records: list[dict]) -> None:
        with open(self.out_dir / f"{name}.jsonl", "a") as f:
            for r in records:
                f.write(json.dumps(r, default=str) + "\n")

    def write_rows(self, table: str, rows: list[tuple]) -> None:
        cols = self.COLUMNS[table]
        self._append(table, [dict(zip(cols, r)) for r in rows])

    def add_surfaces(self, keyframe_sec: float, surfaces: list[Surface]) -> None:
        self._append("surfaces", [
            {"keyframe_sec": keyframe_sec, "surface_id": s.surface_id, "label": s.label,
             "designation": s.designation, "source": s.source, "conf": s.conf, "area_px": s.area,
             "polygon": s.polygon}
            for s in surfaces
        ])

    def finish(self, identity: IdentityResolver) -> None:
        self.flush()
        people = people_summary(identity)
        for p in people:
            p.pop("mean_embedding")
        summary = {
            "session_id": self.session_id,
            "people": people,
            "track_identity": {str(k): v for k, v in identity.track_to_label.items()},
            "row_counts": self.counts,
        }
        (self.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
