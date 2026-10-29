"""MM-OR frames -> YOLO pose dataset for adapting the person/keypoint model to the OR.

MM-OR has no 2D keypoint labels, so a large teacher (yolo26x-pose) labels the
keypoints and MM-OR's ground-truth person masks decide which detections are real:

- a teacher detection is kept only if it matches a ground-truth staff member
  (box IoU), so drapes, equipment and the draped patient stop being "people";
- a frame is kept only if every ground-truth staff member was matched, so the
  student is never taught that a real person is background.

The result teaches the student (e.g. yolo26m-pose) what gowned, masked,
partly occluded OR staff look like from ceiling-mounted cameras.

    python -m training.build_pose_dataset --mmor /data/MM-OR_data --out /data/rescrub_pose --device 0
"""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
import yaml

from .build_seg_dataset import SPLIT_DIRS, _place_image
from .mmor import ClassMap, iter_annotated_frames, person_regions, read_label_mask

COCO_FLIP_IDX = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]


def box_iou(a, b) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_people(gt_boxes: list, det_boxes: np.ndarray, min_iou: float) -> dict[int, int] | None:
    """Greedy one-to-one match gt -> detection. None if any ground-truth person is unmatched."""
    pairs = sorted(
        ((box_iou(g, d), gi, di) for gi, g in enumerate(gt_boxes) for di, d in enumerate(det_boxes)), reverse=True
    )
    matched: dict[int, int] = {}
    used: set[int] = set()
    for iou, gi, di in pairs:
        if iou < min_iou:
            break
        if gi in matched or di in used:
            continue
        matched[gi] = di
        used.add(di)
    return matched if len(matched) == len(gt_boxes) else None


def pose_label_line(box, kps: np.ndarray, w: int, h: int, kp_conf: float) -> str:
    x1, y1, x2, y2 = box
    vals = [0, (x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h]
    for x, y, c in kps:
        vals += [x / w, y / h, 2] if c >= kp_conf else [0, 0, 0]
    return " ".join(f"{v:.5f}" if isinstance(v, float) else str(v) for v in vals) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmor", type=Path)
    ap.add_argument("--or4d", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--teacher", default="yolo26x-pose.pt")
    ap.add_argument("--device", default="0")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--min-iou", type=float, default=0.5)
    ap.add_argument("--kp-conf", type=float, default=0.5, help="teacher keypoint confidence to count as visible")
    ap.add_argument("--no-simstation", action="store_true")
    ap.add_argument("--copy-max-side", type=int, default=None)
    args = ap.parse_args()
    from ultralytics import YOLO

    classes = ClassMap.load()
    teacher = YOLO(args.teacher)
    for d in ("train", "val", "test"):
        (args.out / "images" / d).mkdir(parents=True, exist_ok=True)
        (args.out / "labels" / d).mkdir(parents=True, exist_ok=True)

    seen: Counter = Counter()
    stats: Counter = Counter()
    for split, frame in iter_annotated_frames(args.mmor, {"train", "val", "test"}, args.or4d,
                                              not args.no_simstation):
        key = (frame.dataset, frame.take, frame.camera)
        seen[key] += 1
        if (seen[key] - 1) % args.every:
            continue
        labels = read_label_mask(frame.mask)
        gt = person_regions(labels, classes)
        r = teacher.predict(str(frame.image), classes=[0], conf=0.25, device=args.device, verbose=False)[0]
        h, w = r.orig_shape
        det_boxes = r.boxes.xyxy.cpu().numpy() if r.boxes is not None else np.zeros((0, 4))
        # Mask coordinates may be at a different resolution than the RGB image.
        sy, sx = h / labels.shape[0], w / labels.shape[1]
        gt_boxes = [(b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy) for _, _, b, _ in gt]
        match = match_people(gt_boxes, det_boxes, args.min_iou)
        if match is None:
            stats["skipped_unmatched_person"] += 1
            continue
        kps = r.keypoints.data.cpu().numpy() if r.keypoints is not None else np.zeros((0, 17, 3))
        lines = [pose_label_line(det_boxes[di], kps[di], w, h, args.kp_conf) for di in match.values()]
        d = SPLIT_DIRS[split]
        _place_image(frame.image, args.out / "images" / d / f"{frame.uid}.jpg", args.copy_max_side)
        (args.out / "labels" / d / f"{frame.uid}.txt").write_text("".join(lines))
        stats[f"images_{d}"] += 1
        stats[f"people_{d}"] += len(lines)
        stats["dropped_false_positives"] += len(det_boxes) - len(lines)

    data = {"path": str(args.out.resolve()), "train": "images/train", "val": "images/val", "test": "images/test",
            "kpt_shape": [17, 3], "flip_idx": COCO_FLIP_IDX, "names": {0: "person"}}
    (args.out / "dataset.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    (args.out / "stats.json").write_text(json.dumps(dict(stats), indent=2))
    print(json.dumps(dict(stats)))


if __name__ == "__main__":
    os.environ.setdefault("YOLO_VERBOSE", "false")
    main()
