"""MM-OR panoptic masks -> YOLO segmentation dataset (sterile/nonsterile surfaces + scrubbed/unscrubbed people).

    python -m training.build_seg_dataset --mmor /data/MM-OR_data [--or4d /data/4D-OR_data] --out /data/rescrub_seg

Images are symlinked (MM-OR is large), or resized copies with --copy-max-side.
Writes <out>/dataset.yaml for `python -m training.train seg`.
"""

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

import cv2
import yaml

from .mmor import AnnotatedFrame, ClassMap, class_polygons, iter_annotated_frames, read_label_mask

SPLIT_DIRS = {"train": "train", "short_clips": "train", "val": "val", "test": "test"}


def _place_image(src: Path, dst: Path, copy_max_side: int | None) -> None:
    if dst.exists() or dst.is_symlink():
        return
    if copy_max_side:
        img = cv2.imread(str(src))
        h, w = img.shape[:2]
        s = copy_max_side / max(h, w)
        if s < 1:
            img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    else:
        os.symlink(src.resolve(), dst)


def convert_frame(item: tuple[str, AnnotatedFrame], out: Path, classes: ClassMap, copy_max_side: int | None):
    split, frame = item
    d = SPLIT_DIRS[split]
    labels = read_label_mask(frame.mask)
    polys = class_polygons(labels, classes)
    img_dst = out / "images" / d / f"{frame.uid}.jpg"
    lbl_dst = out / "labels" / d / f"{frame.uid}.txt"
    _place_image(frame.image, img_dst, copy_max_side)
    lbl_dst.write_text("".join(
        f"{cid} " + " ".join(f"{v:.5f}" for v in poly.clip(0, 1).ravel()) + "\n" for cid, poly in polys
    ))
    return d, [cid for cid, _ in polys]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmor", type=Path, help="MM-OR_data folder")
    ap.add_argument("--or4d", type=Path, help="4D-OR_data folder (optional, adds more ORs)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--classes", type=Path, default=None, help="default: training/mmor_classes.yaml")
    ap.add_argument("--every", type=int, default=2, help="keep every Nth annotated frame per camera")
    ap.add_argument("--no-simstation", action="store_true", help="only use the Azure Kinect cameras")
    ap.add_argument("--short-clips", action="store_true", help="also train on MM-OR's short clips")
    ap.add_argument("--copy-max-side", type=int, default=None, help="copy resized images instead of symlinking")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    args = ap.parse_args()
    if not args.mmor and not args.or4d:
        ap.error("give --mmor and/or --or4d")

    classes = ClassMap.load(args.classes) if args.classes else ClassMap.load()
    splits = {"train", "val", "test"} | ({"short_clips"} if args.short_clips else set())
    for d in ("train", "val", "test"):
        (args.out / "images" / d).mkdir(parents=True, exist_ok=True)
        (args.out / "labels" / d).mkdir(parents=True, exist_ok=True)

    per_camera: Counter = Counter()
    items = []
    for split, frame in iter_annotated_frames(args.mmor, splits, args.or4d, not args.no_simstation):
        key = (frame.dataset, frame.take, frame.camera)
        if per_camera[key] % args.every == 0:
            items.append((split, frame))
        per_camera[key] += 1
    print(f"{len(items)} annotated frames selected from {len(per_camera)} camera streams")

    images: Counter = Counter()
    instances: Counter = Counter()
    fn = partial(convert_frame, out=args.out, classes=classes, copy_max_side=args.copy_max_side)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for d, cids in pool.map(fn, items, chunksize=16):
            images[d] += 1
            for c in cids:
                instances[(d, classes.class_names[c])] += 1

    data = {
        "path": str(args.out.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(classes.class_names)),
    }
    (args.out / "dataset.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    stats = {
        "images": dict(images),
        "instances": {f"{d}/{c}": n for (d, c), n in sorted(instances.items())},
        "designation": classes.class_designation,
        "kind": classes.class_kind,
    }
    (args.out / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats["images"]), "->", args.out / "dataset.yaml")


if __name__ == "__main__":
    main()
