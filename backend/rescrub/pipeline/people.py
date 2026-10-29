"""People detection, body keypoints and tracker IDs (YOLO26-pose + BoT-SORT)."""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# COCO-17 indices kept for each person. The analysis cares about arms up to the
# elbow and the hands; shoulders and hips give arm direction and waist level.
BODY_PARTS = {
    5: "l_shoulder",
    6: "r_shoulder",
    7: "l_elbow",
    8: "r_elbow",
    9: "l_wrist",
    10: "r_wrist",
    11: "l_hip",
    12: "r_hip",
}


@dataclass
class PersonObs:
    """One person in one frame."""

    track_id: int
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    conf: float
    # part name -> (x, y, conf)
    points: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    embedding: np.ndarray | None = None
    person_label: str = ""
    designation: str = "sterile"  # scrubbed unless the OR role model says otherwise


class PersonTracker:
    def __init__(self, model_path: str, tracker_config: Path, device: str, embed_model: str | None = None):
        from ultralytics import YOLO

        self.model = YOLO(model_path)
        self.tracker_config = str(tracker_config)
        self.device = device
        self.embedder = YOLO(embed_model) if embed_model else None

    def track(self, frame: np.ndarray) -> list[PersonObs]:
        r = self.model.track(
            frame, persist=True, tracker=self.tracker_config, classes=[0], device=self.device, verbose=False
        )[0]
        if r.boxes is None or r.boxes.id is None or len(r.boxes) == 0:
            return []
        boxes = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int)
        confs = r.boxes.conf.cpu().numpy()
        kps = r.keypoints.data.cpu().numpy() if r.keypoints is not None else None

        out = []
        for i in range(len(ids)):
            points = {}
            if kps is not None:
                for k, name in BODY_PARTS.items():
                    x, y, c = kps[i, k]
                    if c > 0:
                        points[name] = (float(x), float(y), float(c))
            out.append(PersonObs(int(ids[i]), tuple(map(float, boxes[i])), float(confs[i]), points))
        return out

    def embed(self, frame: np.ndarray, people: list[PersonObs]) -> None:
        """Attach an appearance embedding to each person (for identity merging)."""
        if not self.embedder or not people:
            return
        h, w = frame.shape[:2]
        crops = []
        for p in people:
            x1, y1, x2, y2 = (int(round(v)) for v in p.box)
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            crops.append(frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else frame[0:2, 0:2])
        feats = self.embedder.embed(crops, device=self.device, verbose=False)
        for p, f in zip(people, feats):
            v = f.cpu().numpy().astype(np.float32).ravel()
            n = np.linalg.norm(v)
            p.embedding = v / n if n else v
