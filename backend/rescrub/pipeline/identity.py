"""Stable anonymous labels ("Person 1", "Person 2", ...) across the recording.

Everyone wears the same gown, so the tracker loses and re-creates IDs whenever
people cross or are occluded. When a new tracker ID appears, we try to match it
to a person who is not visible right now, using appearance similarity and a
plausible-movement check. Only if nothing matches is a new person created.
"""

from collections import Counter
from dataclasses import dataclass, field

import numpy as np


@dataclass
class _Person:
    label: str
    first_seen: float
    last_seen: float
    last_center: tuple[float, float]
    emb_sum: np.ndarray | None = None
    emb_n: int = 0
    frames_seen: int = 0
    role_votes: Counter = field(default_factory=Counter)
    last_track: int = -1

    @property
    def designation(self) -> str:
        """Scrubbed (sterile) unless a role model has seen this person as unscrubbed more often."""
        return self.role_votes.most_common(1)[0][0] if self.role_votes else "sterile"

    @property
    def mean_embedding(self) -> np.ndarray | None:
        if self.emb_sum is None or self.emb_n == 0:
            return None
        v = self.emb_sum / self.emb_n
        n = np.linalg.norm(v)
        return v / n if n else v


def _center(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


class IdentityResolver:
    def __init__(
        self,
        frame_diag: float,
        similarity: float = 0.80,
        max_gap_sec: float = 30.0,
        max_speed_frac: float = 0.6,
    ):
        self.similarity = similarity
        self.max_gap_sec = max_gap_sec
        self.max_speed_px = max_speed_frac * frame_diag
        self.base_radius = 0.15 * frame_diag
        self.people: dict[str, _Person] = {}
        self.track_to_label: dict[int, str] = {}
        self.track_first_seen: dict[int, float] = {}
        self._seen_this_frame: set[str] = set()

    def assign(self, observations, t: float) -> None:
        """Set `person_label` on every PersonObs seen in the frame at time t.

        Each person gets at most one observation per frame. If two tracker IDs map to
        the same person (an old ID came back after its person was re-identified under
        a new one), the ID that person was last seen with keeps the label and the
        other is matched again like a new track.
        """
        by_label: dict[str, list] = {}
        unresolved = []
        for o in observations:
            label = self.track_to_label.get(o.track_id)
            if label is None:
                unresolved.append(o)
            else:
                by_label.setdefault(label, []).append(o)
        self._seen_this_frame = set(by_label)
        for label, obs in by_label.items():
            keep = next((o for o in obs if o.track_id == self.people[label].last_track), obs[0])
            unresolved += [o for o in obs if o is not keep]
            keep.person_label = label
            self._update(self.people[label], keep, t)
        for o in unresolved:
            label = self._match(o, t) or self._new_person(o, t)
            self.track_to_label[o.track_id] = label
            self.track_first_seen.setdefault(o.track_id, t)
            self._seen_this_frame.add(label)
            o.person_label = label
            self._update(self.people[label], o, t)

    def apply_roles(self, observations, roles, min_iou: float = 0.3) -> None:
        """Vote each person's designation from role masks (one role mask -> at most one person).

        A role mask belongs to the person box it overlaps best (mask-vs-box IoU), so a
        large box that merely contains a neighbour does not take their role.
        """
        taken: set[str] = set()
        for role in sorted(roles, key=lambda r: -r.conf):
            area = int(role.mask.sum())
            if not area:
                continue
            best, best_iou = None, min_iou
            for o in observations:
                if o.person_label in taken:
                    continue
                x1, y1, x2, y2 = (max(0, int(v)) for v in o.box)
                inter = int(role.mask[y1:y2, x1:x2].sum())
                iou = inter / (area + (x2 - x1) * (y2 - y1) - inter)
                if iou > best_iou:
                    best, best_iou = o, iou
            if best is not None:
                taken.add(best.person_label)
                self.people[best.person_label].role_votes[role.designation] += role.conf

    def designation(self, label: str) -> str:
        return self.people[label].designation

    def _match(self, o, t: float) -> str | None:
        c = _center(o.box)
        best, best_score = None, -1.0
        for p in self.people.values():
            if p.label in self._seen_this_frame:
                continue
            gap = t - p.last_seen
            if gap > self.max_gap_sec:
                continue
            dist = float(np.hypot(c[0] - p.last_center[0], c[1] - p.last_center[1]))
            if dist > self.base_radius + self.max_speed_px * gap:
                continue
            mean = p.mean_embedding
            if o.embedding is not None and mean is not None:
                score = float(np.dot(o.embedding, mean))
                if score < self.similarity:
                    continue
            elif gap <= 1.0 and dist <= self.base_radius:
                # No appearance yet: only accept a short, nearby re-appearance.
                score = 1.0 - dist / (self.base_radius + 1e-6)
            else:
                continue
            if score > best_score:
                best, best_score = p.label, score
        return best

    def _new_person(self, o, t: float) -> str:
        label = f"Person {len(self.people) + 1}"
        self.people[label] = _Person(label, t, t, _center(o.box))
        return label

    @staticmethod
    def _update(p: _Person, o, t: float) -> None:
        p.last_seen = t
        p.last_center = _center(o.box)
        p.last_track = o.track_id
        p.frames_seen += 1
        if o.embedding is not None:
            p.emb_sum = o.embedding.copy() if p.emb_sum is None else p.emb_sum + o.embedding
            p.emb_n += 1
