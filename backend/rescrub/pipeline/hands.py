"""Hand and finger points (RTMW whole-body via rtmlib).

COCO pose stops at the wrist, so each tracked person's box is passed to RTMW,
which returns 133 COCO-WholeBody points; we keep the hand wrist and fingertips.
"""

import logging

import numpy as np

from .people import PersonObs

log = logging.getLogger(__name__)

# COCO-WholeBody: left hand 91..111, right hand 112..132 (21 points each).
_HAND_POINTS = {0: "hand_wrist", 4: "thumb_tip", 8: "index_tip", 12: "middle_tip", 16: "ring_tip", 20: "pinky_tip"}
HAND_PARTS = {
    **{91 + k: f"l_{name}" for k, name in _HAND_POINTS.items()},
    **{112 + k: f"r_{name}" for k, name in _HAND_POINTS.items()},
}
MIN_SCORE = 0.3


BOX_MARGIN = 0.15      # hand points may reach this far outside the person box (fraction of its size)
MAX_WRIST_GAP = 0.25   # a hand's wrist must be this close to the pose wrist (fraction of the box diagonal)


def own_hand_points(found: dict[str, tuple[float, float, float]], box: tuple[float, float, float, float],
                    pose: dict[str, tuple[float, float, float]]) -> dict[str, tuple[float, float, float]]:
    """The hand points that belong to this person.

    RTMW reads each person's crop on its own, so near a neighbour it can return the neighbour's hand,
    or points in empty space. Points outside the (slightly enlarged) person box are dropped, and a
    whole hand is dropped when its wrist is far from this person's pose wrist.
    """
    x1, y1, x2, y2 = box
    mx, my = BOX_MARGIN * (x2 - x1), BOX_MARGIN * (y2 - y1)
    max_gap = MAX_WRIST_GAP * float(np.hypot(x2 - x1, y2 - y1))
    kept: dict[str, tuple[float, float, float]] = {}
    for side in ("l", "r"):
        hand = {n: v for n, v in found.items()
                if n.startswith(side + "_") and x1 - mx <= v[0] <= x2 + mx and y1 - my <= v[1] <= y2 + my}
        anchor = hand.get(f"{side}_hand_wrist")
        wrist = pose.get(f"{side}_wrist")
        if anchor is None and hand:
            anchor = (float(np.mean([v[0] for v in hand.values()])), float(np.mean([v[1] for v in hand.values()])), 0)
        if wrist is not None and anchor is not None and np.hypot(anchor[0] - wrist[0], anchor[1] - wrist[1]) > max_gap:
            continue
        kept.update(hand)
    return kept


class HandEstimator:
    def __init__(self, model: str, input_size: tuple[int, int], device: str):
        from rtmlib import RTMPose

        backend_device = "cuda" if device.startswith("cuda") else "cpu"
        if backend_device == "cuda":
            import onnxruntime

            if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
                log.warning("onnxruntime has no CUDA provider; the hand model runs on the CPU (slow). "
                            "Rebuild the worker image, or reinstall onnxruntime-gpu.")
        self.model = RTMPose(model, model_input_size=tuple(input_size), backend="onnxruntime", device=backend_device)

    def add_hands(self, frame: np.ndarray, people: list[PersonObs]) -> None:
        if not people:
            return
        boxes = [list(p.box) for p in people]
        keypoints, scores = self.model(frame, bboxes=boxes)
        for p, kps, sc in zip(people, keypoints, scores):
            found = {}
            for idx, name in HAND_PARTS.items():
                s = float(sc[idx])
                if s >= MIN_SCORE:
                    # SimCC scores can exceed 1; clamp so every `conf` shares a 0..1 scale.
                    found[name] = (float(kps[idx][0]), float(kps[idx][1]), min(1.0, s))
            p.points.update(own_hand_points(found, p.box, p.points))


def load_hand_estimator(settings, device: str) -> HandEstimator | None:
    if not settings.enable_hands:
        return None
    try:
        return HandEstimator(settings.hand_model, settings.hand_input_size, device)
    except Exception as e:  # model download blocked, missing onnxruntime, ...
        log.warning("Hand model unavailable, continuing with wrist points only: %s", e)
        return None
