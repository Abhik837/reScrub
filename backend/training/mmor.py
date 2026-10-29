"""Reads the MM-OR (and optionally 4D-OR) dataset layout.

Expected layout after running MM-OR's download script (one folder per take):

    MM-OR_data/
      001_PKA/
        colorimage/camera01_colorimage-000123.jpg           # Azure Kinect RGB, 2048x1536 (not in every take)
        segmentation_export_1/camera01_colorimage-000123.png  # panoptic mask, pixel = label id
        simstation/camera00_000123.jpg                     # angled ceiling cameras 0/2/3, 1280x720, every take
        simstation_segmentation_export_0/camera00_000123.png
        relation_labels/000045.json                        # scene graph for labeled frame 45
        timestamp_to_pcd_and_frames_list.json              # labeled frame index -> image ids + original_timestamp
      take_jsons/001_PKA.json                              # every frame -> image ids + original_timestamp
      take_timestamp_to_sterility_breach/001_PKA.json      # labeled frame -> [[subject, object, predicate]]

    Images are captured at 1 frame per second; original_timestamp is in seconds.
      015-018_PKA/ ...                                     # several short takes in one folder
    4D-OR_data/export_holistic_take1_processed/ ...        # same mask layout, cameras 1-6

Splits match the MM-OR paper so our numbers are comparable to theirs.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

CLASSES_YAML = Path(__file__).resolve().parent / "mmor_classes.yaml"

MMOR_SPLITS = {
    "train": ["001_PKA", "003_TKA", "005_TKA", "006_PKA", "008_PKA", "010_PKA", "012_1_PKA", "012_2_PKA", "035_PKA",
              "037_TKA"],
    "val": ["002_PKA", "007_TKA", "009_TKA"],
    "test": ["004_PKA", "011_TKA", "036_PKA", "038_TKA"],
    "short_clips": ["013_PKA", "014_PKA", "015_PKA", "016_PKA", "017_PKA", "018_1_PKA", "018_2_PKA", "019_PKA",
                    "020_PKA", "021_PKA", "022_PKA", "023_PKA", "024_PKA", "025_PKA", "026_PKA", "027_PKA", "028_PKA",
                    "029_PKA", "030_PKA", "031_PKA", "032_PKA", "033_PKA"],
}
MMOR_TAKE_TO_FOLDER = {
    "012_1_PKA": "012_PKA", "012_2_PKA": "012_PKA",
    **{t: "015-018_PKA" for t in ["015_PKA", "016_PKA", "017_PKA", "018_1_PKA", "018_2_PKA"]},
    **{t: "019-022_PKA" for t in ["019_PKA", "020_PKA", "021_PKA", "022_PKA"]},
    **{f"0{n}_PKA": "023-032_PKA" for n in range(23, 33)},
}
OR4D_SPLITS = {"train": [1, 3, 5, 7, 9, 10], "val": [4, 8], "test": [2, 6]}

_AZURE_MASK_DIR = re.compile(r"^segmentation_export_(\d+)$")
_SIM_MASK_DIR = re.compile(r"^simstation_segmentation_export_(\d+)$")


@dataclass(frozen=True)
class ClassMap:
    label_to_class: dict[int, str]          # MM-OR label id -> train class
    label_to_kind: dict[int, str]
    class_names: list[str]                  # index = YOLO class id
    class_designation: dict[str, str]
    class_kind: dict[str, str]
    ignore_labels: frozenset[int]
    relation_entities: dict[str, str]
    contact_predicates: frozenset[str]

    @classmethod
    def load(cls, path: Path = CLASSES_YAML) -> "ClassMap":
        cfg = yaml.safe_load(Path(path).read_text())
        label_to_class, label_to_kind, designation, kind = {}, {}, {}, {}
        names: list[str] = []
        for label, e in cfg["labels"].items():
            if e["kind"] == "ignore":
                continue
            c = e["train_class"]
            label_to_class[int(label)] = c
            label_to_kind[int(label)] = e["kind"]
            if c in designation and designation[c] != e["designation"]:
                raise ValueError(f"train_class {c!r} has conflicting designations")
            designation[c], kind[c] = e["designation"], e["kind"]
            if c not in names:
                names.append(c)
        return cls(label_to_class, label_to_kind, names, designation, kind, frozenset(cfg.get("ignore_labels", [])),
                   cfg.get("relation_entities", {}), frozenset(cfg.get("contact_predicates", [])))

    def class_id(self, label: int) -> int | None:
        c = self.label_to_class.get(label)
        return None if c is None else self.class_names.index(c)


@dataclass(frozen=True)
class AnnotatedFrame:
    dataset: str        # "mmor" | "4dor"
    take: str           # e.g. "001_PKA" or "001_4DOR" (folder-level for combined MM-OR folders)
    camera: str         # e.g. "azure1", "simstation0"
    image: Path
    mask: Path

    @property
    def uid(self) -> str:
        return f"{self.dataset}_{self.take}_{self.camera}_{self.image.stem}"


def resolve_root(root: Path) -> Path:
    """MM-OR's zips unpack into MM-OR_data/MM-OR_processed/; accept either folder."""
    root = Path(root)
    return root / "MM-OR_processed" if (root / "MM-OR_processed").is_dir() else root


def _folder_split_mmor(folder: str) -> str | None:
    takes = [t for t, f in MMOR_TAKE_TO_FOLDER.items() if f == folder] or [folder]
    for split, members in MMOR_SPLITS.items():
        if any(t in members for t in takes):
            return split
    return None


def _folder_split_4dor(folder: str) -> tuple[str | None, str]:
    m = re.search(r"take(\d+)", folder)
    if not m:
        return None, folder
    n = int(m.group(1))
    split = next((s for s, takes in OR4D_SPLITS.items() if n in takes), None)
    return split, f"{n:03d}_4DOR"


def iter_annotated_frames(
    mmor_root: Path | None, splits: set[str], or4d_root: Path | None = None, include_simstation: bool = True
) -> Iterator[tuple[str, AnnotatedFrame]]:
    """Yield (split, frame) for every RGB frame that has a non-interpolated mask."""
    roots: list[tuple[str, Path]] = []
    if mmor_root:
        roots.append(("mmor", resolve_root(mmor_root)))
    if or4d_root:
        roots.append(("4dor", Path(or4d_root)))
    for dataset, root in roots:
        for take_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if dataset == "mmor":
                split, take = _folder_split_mmor(take_dir.name), take_dir.name
            else:
                split, take = _folder_split_4dor(take_dir.name)
            if split not in splits:
                continue
            for mask_dir in sorted(p for p in take_dir.iterdir() if p.is_dir()):
                if m := _AZURE_MASK_DIR.match(mask_dir.name):
                    camera, image_dir = f"azure{m.group(1)}", take_dir / "colorimage"
                elif include_simstation and (m := _SIM_MASK_DIR.match(mask_dir.name)):
                    camera, image_dir = f"simstation{m.group(1)}", take_dir / "simstation"
                else:
                    continue
                for mask in sorted(mask_dir.glob("*.png")):
                    if mask.stem.endswith("_interpolated"):
                        continue  # MM-OR does not train on interpolated masks
                    image = image_dir / f"{mask.stem}.jpg"
                    if image.exists():
                        yield split, AnnotatedFrame(dataset, take, camera, image, mask)


def read_label_mask(path: Path, min_component_px: int = 10) -> np.ndarray:
    """HxW uint8 label image, cleaned the same way MM-OR's loader does."""
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    labels = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for lab in np.unique(labels):
        if lab == 0:
            continue
        binary = (labels == lab).astype(np.uint8)
        n, cc, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < min_component_px:
                labels[cc == i] = 0
    return labels


def class_polygons(
    labels: np.ndarray, classes: ClassMap, min_area_frac: float = 0.0004, kinds: set[str] | None = None
) -> list[tuple[int, np.ndarray]]:
    """[(class_id, Nx2 normalized polygon)] — one polygon per connected region of each class."""
    h, w = labels.shape
    min_area = min_area_frac * h * w
    out: list[tuple[int, np.ndarray]] = []
    # Several MM-OR labels can share one train class (e.g. drill/saw -> instrument): merge first.
    by_class: dict[int, np.ndarray] = {}
    for lab in np.unique(labels):
        lab = int(lab)
        if lab == 0 or lab in classes.ignore_labels:
            continue
        cid = classes.class_id(lab)
        if cid is None or (kinds and classes.label_to_kind[lab] not in kinds):
            continue
        m = labels == lab
        by_class[cid] = by_class[cid] | m if cid in by_class else m
    for cid, m in sorted(by_class.items()):
        contours, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if cv2.contourArea(c) < min_area:
                continue
            c = cv2.approxPolyDP(c, 0.002 * cv2.arcLength(c, True), True).reshape(-1, 2)
            if len(c) < 3:
                continue
            out.append((cid, c.astype(np.float32) / [w, h]))
    return out


def person_regions(labels: np.ndarray, classes: ClassMap, min_area_frac: float = 0.002):
    """[(mmor_label, train_class, (x1, y1, x2, y2), mask)] for each staff member in the frame.

    Each MM-OR role (head_surgeon, circulator, ...) is one person per frame, so the
    label itself is the identity within a take.
    """
    h, w = labels.shape
    out = []
    for lab in np.unique(labels):
        lab = int(lab)
        if classes.label_to_kind.get(lab) != "person":
            continue
        m = labels == lab
        if m.sum() < min_area_frac * h * w:
            continue
        ys, xs = np.nonzero(m)
        out.append((lab, classes.label_to_class[lab], (int(xs.min()), int(ys.min()), int(xs.max()) + 1,
                                                        int(ys.max()) + 1), m))
    return out


def load_relation_frames(take_dir: Path, take: str) -> Iterator[tuple[int, list[tuple[str, str, str]], dict]]:
    """Yield (frame_index, [(subject, predicate, object)], image ids) for one MM-OR take."""
    rel_dir = take_dir / "relation_labels"
    if not rel_dir.exists():
        rel_dir = take_dir / f"relation_labels_{take}"
    ts_path = take_dir / f"timestamp_to_pcd_and_frames_list_{take}.json"
    if not ts_path.exists():
        ts_path = take_dir / "timestamp_to_pcd_and_frames_list.json"
    if not rel_dir.exists() or not ts_path.exists():
        return
    timestamps = json.loads(ts_path.read_text())
    for p in sorted(rel_dir.glob("*.json")):
        idx = int(p.stem)
        rels = json.loads(p.read_text()).get("rel_annotations", [])
        ids = timestamps[idx][1] if idx < len(timestamps) else {}
        yield idx, [(s, pr, o) for s, pr, o, *_ in rels], ids


def normalize_entity(name: str) -> str:
    n = name.lower().replace("-", "_")
    return {"ot": "operating_table", "ae": "anesthesia_equipment", "anest": "anaesthetist",
            "circulating_nurse": "circulator"}.get(n, n)
