"""Draw labels, tracks and surfaces onto the recording and encode H.264 for browsers."""

import subprocess
from collections import defaultdict, deque
from pathlib import Path

import cv2
import numpy as np

from .people import PersonObs
from .proximity import ProximityRow
from .surfaces import Surface

# BGR
STERILE = (90, 190, 60)
NONSTERILE = (60, 60, 230)
PATIENT = (40, 150, 245)
NEUTRAL = (170, 170, 170)
DESIGNATION_COLOR = {"sterile": STERILE, "nonsterile": NONSTERILE, "patient": PATIENT, "neutral": NEUTRAL}
DESIGNATION_TAG = {"sterile": "STERILE", "nonsterile": "NON-STERILE", "patient": "PATIENT", "neutral": "NEUTRAL"}
WHITE = (245, 245, 245)
BLACK = (20, 20, 20)
PERSON_COLORS = [
    (230, 160, 40), (40, 200, 230), (200, 90, 220), (80, 220, 160),
    (240, 120, 120), (120, 160, 255), (60, 140, 240), (200, 200, 80),
]
FONT = cv2.FONT_HERSHEY_SIMPLEX
ARM_LINKS = [("l_shoulder", "l_elbow"), ("l_elbow", "l_wrist"), ("r_shoulder", "r_elbow"), ("r_elbow", "r_wrist")]
FINGERS = ["thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip"]
TRAIL_PARTS = ("l_wrist", "r_wrist")
TRAIL_SEC = 1.0  # trails show the last second of movement (none on 1 frame/s footage)


def person_color(label: str) -> tuple[int, int, int]:
    try:
        n = int(label.split()[-1])
    except ValueError:
        n = abs(hash(label))
    return PERSON_COLORS[(n - 1) % len(PERSON_COLORS)]


def _text(img, text, org, scale=0.5, color=WHITE, bg=BLACK, thickness=1):
    (tw, th), base = cv2.getTextSize(text, FONT, scale, thickness)
    x, y = int(org[0]), int(org[1])
    cv2.rectangle(img, (x - 2, y - th - 4), (x + tw + 2, y + base), bg, -1)
    cv2.putText(img, text, (x, y), FONT, scale, color, thickness, cv2.LINE_AA)


def format_ts(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:06.3f}"


class AnnotatedVideoWriter:
    """Pipes raw frames into ffmpeg -> H.264 / yuv420p / faststart MP4."""

    def __init__(self, path: Path, width: int, height: int, fps: float):
        self.path = Path(path)
        self.size = (width, height)
        self.proc = subprocess.Popen(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.6f}", "-i", "-",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(self.path),
            ],
            stdin=subprocess.PIPE,
        )
        self._surface_key = None
        self._overlay = None
        self._overlay_mask = None
        self._trails: dict[tuple[str, str], deque] = defaultdict(deque)

    def write(
        self,
        frame: np.ndarray,
        frame_idx: int,
        t: float,
        people: list[PersonObs],
        surfaces: list[Surface],
        rows: list[ProximityRow],
    ) -> None:
        img = self._draw_surfaces(frame.copy(), surfaces)
        self._draw_people(img, people, t)
        self._draw_contacts(img, people, rows)
        self._draw_hud(img, frame_idx, t, len(people))
        self.proc.stdin.write(np.ascontiguousarray(img).tobytes())

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        if self.proc.wait(timeout=600) != 0:
            raise RuntimeError("ffmpeg failed to encode the annotated video")

    def abort(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()

    def _draw_surfaces(self, img: np.ndarray, surfaces: list[Surface]) -> np.ndarray:
        key = tuple(id(s) for s in surfaces)
        if key != self._surface_key:
            self._surface_key = key
            self._overlay = np.zeros_like(img)
            self._overlay_mask = np.zeros(img.shape[:2], bool)
            for s in surfaces:
                self._overlay[s.mask] = DESIGNATION_COLOR[s.designation]
                self._overlay_mask |= s.mask
        if surfaces:
            m = self._overlay_mask
            img[m] = (img[m] * 0.65 + self._overlay[m] * 0.35).astype(np.uint8)
        for s in surfaces:
            color = DESIGNATION_COLOR[s.designation]
            if len(s.polygon) >= 3:
                poly = np.asarray(s.polygon, np.int32)
                cv2.polylines(img, [poly], True, color, 2, cv2.LINE_AA)
                cx, cy = poly.mean(axis=0)
                _text(img, f"{s.label} [{DESIGNATION_TAG[s.designation]}]", (cx - 40, cy), 0.45, WHITE, color)
        return img

    def _draw_people(self, img: np.ndarray, people: list[PersonObs], t: float) -> None:
        for p in people:
            color = person_color(p.person_label)
            x1, y1, x2, y2 = (int(v) for v in p.box)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            tag = "scrubbed" if p.designation == "sterile" else "unscrubbed"
            _text(img, f"{p.person_label} ({tag})", (x1 + 2, max(14, y1 - 4)), 0.55, BLACK, color, 1)
            if p.designation != "sterile":
                cv2.rectangle(img, (x1 + 3, y1 + 3), (x2 - 3, y2 - 3), NONSTERILE, 1)
            pts = p.points
            for a, b in ARM_LINKS:
                if a in pts and b in pts:
                    cv2.line(img, (int(pts[a][0]), int(pts[a][1])), (int(pts[b][0]), int(pts[b][1])), color, 3,
                             cv2.LINE_AA)
            for side in ("l", "r"):
                w = pts.get(f"{side}_hand_wrist") or pts.get(f"{side}_wrist")
                for f in FINGERS:
                    tip = pts.get(f"{side}_{f}")
                    if w and tip:
                        cv2.line(img, (int(w[0]), int(w[1])), (int(tip[0]), int(tip[1])), color, 1, cv2.LINE_AA)
            for name, (x, y, _c) in pts.items():
                if "hip" in name:
                    continue
                cv2.circle(img, (int(x), int(y)), 4 if "tip" not in name else 2, WHITE, -1, cv2.LINE_AA)
            for part in TRAIL_PARTS:
                trail = self._trails[(p.person_label, part)]
                if part in pts:
                    trail.append((t, int(pts[part][0]), int(pts[part][1])))
                while trail and t - trail[0][0] > TRAIL_SEC:
                    trail.popleft()
                if len(trail) > 1:
                    cv2.polylines(img, [np.asarray([xy for _, *xy in trail], np.int32)], False, color, 1,
                                  cv2.LINE_AA)

    @staticmethod
    def _draw_contacts(img: np.ndarray, people: list[PersonObs], rows: list[ProximityRow]) -> None:
        pts = {(p.person_label, k): v for p in people for k, v in p.points.items()}
        y = 52
        listed = set()
        for r in rows:
            if not r.candidate_contact:
                continue
            x, yy, _ = pts[(r.person_label, r.part)]
            color = DESIGNATION_COLOR.get(r.designation, NONSTERILE)
            cv2.circle(img, (int(x), int(yy)), 12, color, 2, cv2.LINE_AA)
            if r.designation in ("nonsterile", "patient") and (r.person_label, r.surface_id) not in listed:
                listed.add((r.person_label, r.surface_id))
                _text(img, f"{r.person_label} near/touching {r.surface_id}", (10, y), 0.5, WHITE, color)
                y += 22

    @staticmethod
    def _draw_hud(img: np.ndarray, frame_idx: int, t: float, n_people: int) -> None:
        _text(img, f"{format_ts(t)}  frame {frame_idx}  people {n_people}", (10, 24), 0.6)
        h = img.shape[0]
        _text(img, "STERILE", (10, h - 12), 0.5, WHITE, STERILE)
        _text(img, "NON-STERILE", (100, h - 12), 0.5, WHITE, NONSTERILE)
        _text(img, "PATIENT", (230, h - 12), 0.5, WHITE, PATIENT)
