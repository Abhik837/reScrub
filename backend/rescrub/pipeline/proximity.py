"""Hand/arm-to-surface proximity features (inputs to the breach analysis).

Nothing here decides whether contamination happened. Each row describes how
close a tracked point is to a sterile or nonsterile surface at one moment, with
a `candidate_contact` flag (inside or touching the mask, at a similar depth,
moving slowly) that the breach analysis groups into contact events.
"""

from dataclasses import dataclass

import numpy as np

from .people import PersonObs
from .surfaces import Surface

# Points that can make contact: wrists, elbows (forearm) and fingertips.
CONTACT_PARTS = {
    "l_wrist", "r_wrist", "l_elbow", "r_elbow",
    "l_hand_wrist", "l_thumb_tip", "l_index_tip", "l_middle_tip", "l_ring_tip", "l_pinky_tip",
    "r_hand_wrist", "r_thumb_tip", "r_index_tip", "r_middle_tip", "r_ring_tip", "r_pinky_tip",
}
DEPTH_WINDOW = 15  # px radius used to sample surface depth around a point


@dataclass
class ProximityRow:
    person_label: str
    part: str
    surface_id: str
    designation: str
    pixel_dist: float
    inside_mask: bool
    depth_gap: float | None
    speed_px_s: float | None
    candidate_contact: bool
    person_designation: str | None = None  # the person's role at this frame, as the labeled video shows it


def surface_depth_near(depth: np.ndarray, surface: Surface, x: int, y: int) -> float | None:
    h, w = depth.shape
    x0, x1 = max(0, x - DEPTH_WINDOW), min(w, x + DEPTH_WINDOW + 1)
    y0, y1 = max(0, y - DEPTH_WINDOW), min(h, y + DEPTH_WINDOW + 1)
    m = surface.mask[y0:y1, x0:x1]
    if not m.any():
        return None
    return float(np.median(depth[y0:y1, x0:x1][m]))


class ProximityAnalyzer:
    def __init__(self, near_px: float, contact_px: float, contact_depth_gap: float, max_speed_px_s: float):
        self.near_px = near_px
        self.contact_px = contact_px
        self.contact_depth_gap = contact_depth_gap
        self.max_speed = max_speed_px_s
        self._last: dict[tuple[str, str], tuple[float, float, float]] = {}  # (person, part) -> (t, x, y)

    def speed(self, person: str, part: str, x: float, y: float, t: float) -> float | None:
        prev = self._last.get((person, part))
        self._last[(person, part)] = (t, x, y)
        if prev is None or t <= prev[0] or t - prev[0] > 0.5:
            return None
        return float(np.hypot(x - prev[1], y - prev[2]) / (t - prev[0]))

    def analyze(
        self, people: list[PersonObs], surfaces: list[Surface], t: float, depth: np.ndarray | None
    ) -> tuple[list[ProximityRow], dict[tuple[str, str], float]]:
        """Return proximity rows plus each contact point's own depth (for the keypoints table)."""
        rows: list[ProximityRow] = []
        point_depth: dict[tuple[str, str], float] = {}
        for p in people:
            for part, (x, y, _conf) in p.points.items():
                xi, yi = int(round(x)), int(round(y))
                if depth is not None and 0 <= yi < depth.shape[0] and 0 <= xi < depth.shape[1]:
                    point_depth[(p.person_label, part)] = float(depth[yi, xi])
                if part not in CONTACT_PARTS:
                    continue
                spd = self.speed(p.person_label, part, x, y, t)
                for s in surfaces:
                    h, w = s.mask.shape
                    if not (0 <= yi < h and 0 <= xi < w):
                        continue
                    dist = float(s.dist[yi, xi])
                    if dist > self.near_px:
                        continue
                    inside = bool(s.mask[yi, xi])
                    gap = None
                    if depth is not None:
                        sd = surface_depth_near(depth, s, xi, yi)
                        if sd is not None:
                            gap = point_depth[(p.person_label, part)] - sd
                    candidate = (
                        dist <= self.contact_px
                        and (gap is None or abs(gap) <= self.contact_depth_gap)
                        and (spd is None or spd <= self.max_speed)
                    )
                    rows.append(
                        ProximityRow(p.person_label, part, s.surface_id, s.designation, dist, inside, gap, spd,
                                     candidate, p.designation)
                    )
        return rows, point_depth
