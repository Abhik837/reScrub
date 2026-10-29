"""MM-OR person crops -> identity classification dataset for the ReID embedder.

In every MM-OR take each role (head_surgeon, circulator, ...) is one real
person, so (take, role) is an identity label for free. A classifier trained to
tell those identities apart learns features that separate people in identical
gowns (cap, mask, glasses, build, posture); the tracker then uses its embedding
(EMBED_MODEL) to keep "Person N" labels stable.

Only MM-OR train/val takes are used; test takes stay unseen for the end-to-end
evaluation. Within each take the last --val-frac of frames is held out for
validation, so val measures recognising the same people later in the procedure.

    python -m training.build_reid_dataset --mmor /data/MM-OR_data --out /data/rescrub_reid
"""

import argparse
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from .mmor import ClassMap, iter_annotated_frames, person_regions, read_label_mask


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmor", type=Path)
    ap.add_argument("--or4d", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--crop-size", type=int, default=256, help="longest side of saved crops")
    ap.add_argument("--min-crops", type=int, default=20, help="drop identities with fewer crops")
    args = ap.parse_args()

    classes = ClassMap.load()
    streams = defaultdict(list)  # (dataset, take, camera) -> annotated frames in time order
    # Test takes stay unseen by every model (they are used for the end-to-end evaluation).
    # Short clips are excluded: one folder holds several clips where a role may be played by different people.
    for _split, f in iter_annotated_frames(args.mmor, {"train", "val"}, args.or4d):
        streams[(f.dataset, f.take, f.camera)].append(f)

    stats: Counter = Counter()
    for fs in streams.values():
        fs = fs[:: args.every]
        for i, f in enumerate(fs):
            # Position in the recording decides the split, so val = later in the same procedure.
            d = "val" if i >= len(fs) * (1 - args.val_frac) else "train"
            labels = read_label_mask(f.mask)
            img = cv2.imread(str(f.image))
            sy, sx = img.shape[0] / labels.shape[0], img.shape[1] / labels.shape[1]
            for lab, train_class, (x1, y1, x2, y2), _m in person_regions(labels, classes):
                crop = img[int(y1 * sy):int(y2 * sy), int(x1 * sx):int(x2 * sx)]
                if crop.size == 0:
                    continue
                s = args.crop_size / max(crop.shape[:2])
                if s < 1:
                    crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                identity = f"{f.dataset}_{f.take}_{train_class}_{lab}"
                out = args.out / d / identity
                out.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out / f"{f.camera}_{f.image.stem}.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])

    # Classification needs every identity in both splits with enough examples.
    for ident_dir in sorted((args.out / "train").glob("*")):
        val_dir = args.out / "val" / ident_dir.name
        n_train = len(list(ident_dir.glob("*.jpg")))
        n_val = len(list(val_dir.glob("*.jpg"))) if val_dir.exists() else 0
        if n_train + n_val < args.min_crops or n_val == 0:
            shutil.rmtree(ident_dir)
            shutil.rmtree(val_dir, ignore_errors=True)
            stats["identities_dropped"] += 1
            continue
        stats["identities"] += 1
        stats["crops_train"] += n_train
        stats["crops_val"] += n_val
    for val_only in (args.out / "val").glob("*"):
        if not (args.out / "train" / val_only.name).exists():
            shutil.rmtree(val_only)
    (args.out / "stats.json").write_text(json.dumps(dict(stats), indent=2))
    print(json.dumps(dict(stats)))


if __name__ == "__main__":
    main()
