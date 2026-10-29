"""Sterile / nonsterile surface masks.

Default: open-vocabulary segmentation (YOLOE) prompted with the surfaces listed in
config/surfaces.yaml, re-run every few seconds (the camera is fixed, so surfaces
change slowly). A session may instead provide hand-drawn zones, which are used
as-is for the whole recording. A fine-tuned YOLO26-seg model can replace YOLOE
by changing `model` in the config.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

log = logging.getLogger(__name__)

DESIGNATIONS = ("sterile", "nonsterile", "patient", "neutral")


@dataclass
class Surface:
    surface_id: str
    label: str
    designation: str
    source: str  # "auto" | "manual"
    mask: np.ndarray  # bool HxW
    conf: float | None = None
    polygon: list[list[int]] = field(default_factory=list)
    _dist: np.ndarray | None = field(default=None, repr=False)

    @property
    def area(self) -> int:
        return int(self.mask.sum())

    @property
    def dist(self) -> np.ndarray:
        """Pixel distance from every pixel to the nearest pixel of this surface (0 inside)."""
        if self._dist is None:
            outside = np.where(self.mask, 0, 255).astype(np.uint8)
            self._dist = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
        return self._dist


@dataclass
class PersonRole:
    """A staff member found by a model trained on OR roles (e.g. scrubbed vs. unscrubbed)."""

    label: str        # e.g. "Scrubbed"
    designation: str  # "sterile" (scrubbed) or "nonsterile" (unscrubbed)
    conf: float
    mask: np.ndarray  # bool HxW


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "surface"


def _largest_polygon(mask: np.ndarray) -> list[list[int]]:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    c = max(contours, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, 0.003 * cv2.arcLength(c, True), True)
    return c.reshape(-1, 2).astype(int).tolist()


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / float(union) if union else 0.0


def parse_zones(zones, width: int, height: int) -> list[Surface]:
    """Hand-drawn zones: [{"label", "designation", "polygon": [[x, y], ...]}, ...].

    Coordinates may be pixels or fractions of the frame (all values <= 1).
    Earlier zones win where they overlap.
    """
    if isinstance(zones, str):
        zones = json.loads(zones)
    if not isinstance(zones, list):
        raise ValueError("zones must be a JSON list")
    out: list[Surface] = []
    taken = np.zeros((height, width), bool)
    counts: dict[str, int] = {}
    for z in zones:
        label = str(z.get("label") or "Zone").strip()[:80]
        designation = z.get("designation")
        if designation not in DESIGNATIONS:
            raise ValueError(f"zone '{label}': designation must be one of {', '.join(DESIGNATIONS)}")
        pts = np.asarray(z.get("polygon") or [], dtype=float)
        if pts.ndim != 2 or pts.shape[0] < 3 or pts.shape[1] != 2:
            raise ValueError(f"zone '{label}': polygon needs at least 3 [x, y] points")
        if pts.max() <= 1.0:
            pts = pts * [width, height]
        poly = np.round(pts).astype(np.int32)
        mask = np.zeros((height, width), np.uint8)
        cv2.fillPoly(mask, [poly], 1)
        mask = mask.astype(bool) & ~taken
        taken |= mask
        slug = _slug(label)
        counts[slug] = counts.get(slug, 0) + 1
        out.append(Surface(f"{slug}-{counts[slug]}", label, designation, "manual", mask, None, poly.tolist()))
    return out


class SurfaceSegmenter:
    """Runs the segmentation model and keeps surface IDs stable across keyframes."""

    def __init__(self, config_path: Path, device: str, models_dir: Path | None = None):
        cfg = yaml.safe_load(Path(config_path).read_text())
        # `surfaces` become sterile/nonsterile/patient masks; `people` (only for a model trained
        # on OR roles, e.g. config/surfaces_mmor.yaml) say whether each person is scrubbed.
        self.entries = [{**e, "kind": "surface"} for e in cfg["surfaces"]]
        self.entries += [{**e, "kind": "person"} for e in cfg.get("people", [])]
        for e in self.entries:
            if e["designation"] not in DESIGNATIONS:
                raise ValueError(f"{config_path}: bad designation for {e['prompt']!r}")
        self.conf = float(cfg.get("conf", 0.25))
        self.iou_match = float(cfg.get("iou_match", 0.3))
        self.min_area_frac = float(cfg.get("min_area_frac", 0.002))
        self.device = device

        model_name = cfg["model"]
        model_path = models_dir / model_name if models_dir else model_name
        prompts = [e["prompt"] for e in self.entries]
        if "yoloe" in Path(model_name).name.lower():
            from ultralytics import YOLOE

            self.model = YOLOE(str(model_path))
            self.model.set_classes(prompts, self.model.get_text_pe(prompts))
            self.class_to_entry = dict(enumerate(range(len(prompts))))
        else:  # fine-tuned closed-vocabulary model: prompts are its class names
            from ultralytics import YOLO

            if models_dir and not Path(model_path).exists():
                # Trained weights are never downloaded (MM-OR terms; see README "Trained models").
                raise FileNotFoundError(
                    f"{config_path} needs the trained model {model_path}, which is not there. Put your "
                    "trained weights in models/trained/ or use SURFACE_CONFIG=config/surfaces.yaml.")
            self.model = YOLO(str(model_path))
            by_name = {e["prompt"]: i for i, e in enumerate(self.entries)}
            self.class_to_entry = {c: by_name[n] for c, n in self.model.names.items() if n in by_name}

        self._previous: list[Surface] = []
        self._counts: dict[str, int] = {}
        self.last_people: list[PersonRole] = []  # person roles from the latest segment() call

    def segment(self, frame: np.ndarray) -> list[Surface]:
        h, w = frame.shape[:2]
        r = self.model.predict(frame, conf=self.conf, retina_masks=True, device=self.device, verbose=False)[0]
        found: list[tuple[int, float, np.ndarray]] = []
        if r.masks is not None and r.boxes is not None:
            masks = r.masks.data.cpu().numpy() > 0.5
            for m, c, s in zip(masks, r.boxes.cls.cpu().numpy().astype(int), r.boxes.conf.cpu().numpy()):
                if c in self.class_to_entry:
                    if m.shape != (h, w):
                        m = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
                    found.append((self.class_to_entry[c], float(s), m))

        self.last_people = [
            PersonRole(self.entries[i]["label"], self.entries[i]["designation"], conf, m)
            for i, conf, m in found if self.entries[i]["kind"] == "person"
        ]
        found = [f for f in found if self.entries[f[0]]["kind"] == "surface"]
        # Higher-priority (earlier) entries claim overlapping pixels first.
        found.sort(key=lambda f: (f[0], -f[1]))
        taken = np.zeros((h, w), bool)
        min_area = self.min_area_frac * h * w
        surfaces: list[Surface] = []
        used: set[str] = set()
        for entry_idx, conf, m in found:
            m = m & ~taken
            if m.sum() < min_area:
                continue
            taken |= m
            e = self.entries[entry_idx]
            sid = self._stable_id(e["label"], m, used)
            used.add(sid)
            surfaces.append(Surface(sid, e["label"], e["designation"], "auto", m, conf, _largest_polygon(m)))
        self._previous = surfaces
        return surfaces

    def _stable_id(self, label: str, mask: np.ndarray, used: set[str]) -> str:
        best, best_iou = None, self.iou_match
        for p in self._previous:
            if p.label == label and p.surface_id not in used:
                iou = _iou(p.mask, mask)
                if iou >= best_iou:
                    best, best_iou = p.surface_id, iou
        if best:
            return best
        slug = _slug(label)
        self._counts[slug] = self._counts.get(slug, 0) + 1
        return f"{slug}-{self._counts[slug]}"
