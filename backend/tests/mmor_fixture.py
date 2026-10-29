"""A tiny fake MM-OR dataset with the real on-disk layout, for testing the training tools."""

import json
from pathlib import Path

import cv2
import numpy as np

# label id -> (fill colour BGR, shape)
_SCENE = {
    6: ((200, 120, 60), "drape"),
    1: ((180, 180, 200), "instrument_table"),
    3: ((90, 90, 90), "ot"),
    5: ((150, 170, 230), "patient"),
    10: ((210, 90, 40), "head_surgeon"),
    8: ((60, 160, 60), "circulator"),
}


def _draw(img: np.ndarray, mask: np.ndarray, label: int, pts, scale: float) -> None:
    color, _ = _SCENE[label]
    poly = np.asarray(pts, np.int32)
    cv2.fillPoly(img, [poly], color)
    cv2.fillPoly(mask, [np.round(poly * scale).astype(np.int32)], label)


def make_scene(t: int, w: int = 320, h: int = 240, mask_scale: float = 0.5):
    """One frame: drape on the operating table, instrument table, two people moving."""
    rng = np.random.default_rng(t)
    img = np.full((h, w, 3), 40, np.uint8) + rng.integers(0, 8, (h, w, 3), dtype=np.uint8)
    mask = np.zeros((int(h * mask_scale), int(w * mask_scale)), np.uint8)
    _draw(img, mask, 3, [(80, 150), (240, 150), (240, 200), (80, 200)], mask_scale)        # operating table
    _draw(img, mask, 6, [(90, 110), (230, 110), (230, 160), (90, 160)], mask_scale)         # drape on it
    _draw(img, mask, 5, [(140, 100), (180, 100), (180, 112), (140, 112)], mask_scale)       # exposed patient
    _draw(img, mask, 1, [(250, 60), (310, 60), (310, 120), (250, 120)], mask_scale)         # instrument table
    x = 20 + (t * 7) % 40
    _draw(img, mask, 10, [(x, 30), (x + 40, 30), (x + 45, 140), (x - 5, 140)], mask_scale)   # head surgeon
    _draw(img, mask, 8, [(250, 130), (290, 130), (295, 235), (245, 235)], mask_scale)       # circulator
    cv2.circle(mask, (5, 5), 2, 14, -1)  # an "annotation mistake" label MM-OR ignores
    return img, mask


def make_fake_mmor(root: Path, frames_per_take: int = 6) -> Path:
    """Same layout as the real download: MM-OR_data/MM-OR_processed/<take>/..., 1 frame per second,
    every 2nd frame labeled (masks, scene graph, breach label)."""
    data = root / "MM-OR_processed"
    takes = {"001_PKA": "train", "003_TKA": "train", "002_PKA": "val", "004_PKA": "test"}
    for take in takes:
        d = data / take
        for sub in ("colorimage", "segmentation_export_1", "simstation", "simstation_segmentation_export_0",
                    "relation_labels"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        dense, labeled = {}, []
        for j in range(2 * frames_per_take):  # one image per second
            img, mask = make_scene(j + hash(take) % 5)
            image_id = f"{j + 1:06d}"
            info = {"azure": image_id, "simstation": image_id, "trackercam": None, "tracker": None,
                    "original_timestamp": 100 + j}
            dense[str(j)] = info
            cv2.imwrite(str(d / "colorimage" / f"camera01_colorimage-{image_id}.jpg"), img)
            cv2.imwrite(str(d / "simstation" / f"camera00_{image_id}.jpg"), cv2.flip(img, 1))
            if j % 2:
                continue
            i = len(labeled)  # labeled-frame index: what relation/breach labels are keyed by
            labeled.append([f"{j:06d}", info])
            cv2.imwrite(str(d / "segmentation_export_1" / f"camera01_colorimage-{image_id}.png"),
                        cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))
            cv2.imwrite(str(d / "simstation_segmentation_export_0" / f"camera00_{image_id}.png"), cv2.flip(mask, 1))
            rels = [["head_surgeon", "Touching", "patient"], ["circulator", "Touching", "instrument_table"],
                    ["head_surgeon", "closeTo", "ot"]]
            (d / "relation_labels" / f"{i:06d}.json").write_text(json.dumps({"rel_annotations": rels}))
        # an interpolated mask must be ignored
        cv2.imwrite(str(d / "segmentation_export_1" / "camera01_colorimage-000001_interpolated.png"), mask)
        (d / "timestamp_to_pcd_and_frames_list.json").write_text(json.dumps(labeled))
        (data / "take_jsons").mkdir(exist_ok=True)
        (data / "take_jsons" / f"{take}.json").write_text(json.dumps({"folder": take, "timestamps": dense}))
        # Breach labels: labeled-frame index -> [[subject, object, predicate], ...] (note the order)
        breach_dir = data / "take_timestamp_to_sterility_breach"
        breach_dir.mkdir(exist_ok=True)
        labels = {f"{i:06d}": ([["circulator", "instrument_table", "touching"]] if 2 <= i <= 3 else [])
                  for i in range(frames_per_take)}
        (breach_dir / f"{take}.json").write_text(json.dumps(labels))
    (data / "999_UNKNOWN").mkdir()  # folders outside the splits are skipped
    return root
