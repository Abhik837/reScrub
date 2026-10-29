"""Relative depth from one camera (Depth Anything V2), to tell hovering from touching."""

import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)


class DepthEstimator:
    def __init__(self, model_id: str, device: str):
        from transformers import pipeline

        self.pipe = pipeline("depth-estimation", model=model_id, device=device)

    def estimate(self, frame: np.ndarray) -> np.ndarray:
        """Return a float32 HxW map normalized to 0..1 (larger = closer to the camera)."""
        from PIL import Image

        h, w = frame.shape[:2]
        out = self.pipe(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        d = out["predicted_depth"].squeeze().float().cpu().numpy()
        d = cv2.resize(d, (w, h), interpolation=cv2.INTER_LINEAR)
        lo, hi = np.percentile(d, 1), np.percentile(d, 99)
        return np.clip((d - lo) / (hi - lo + 1e-6), 0, 1).astype(np.float32)


def load_depth_estimator(settings, device: str) -> DepthEstimator | None:
    if not settings.enable_depth:
        return None
    try:
        return DepthEstimator(settings.depth_model, device)
    except Exception as e:  # weights unreachable, transformers missing, ...
        log.warning("Depth model unavailable, depth columns will be empty: %s", e)
        return None
