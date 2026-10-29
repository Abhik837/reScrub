"""Download only the parts of MM-OR that reScrub trains and tests on.

Uses the same files as MM-OR's download_mm-or.sh (you must have accepted the
MM-OR terms of use), but:

- picks takes by split, so test surgeries can be kept for evaluation only;
- skips modalities reScrub does not use (point clouds, audio, transcripts);
- checks free disk space before each file and stops early instead of filling the disk;
- with --prune, deletes unused folders (depth, point clouds, ...) right after unzipping.

    python -m training.fetch_mmor --out /data --profile tiny     # 1 train + 1 val + 1 test surgery
    python -m training.fetch_mmor --out /data --profile small    # 2 train + 1 val + 1 test surgery
    python -m training.fetch_mmor --out /data --profile full     # all main takes (train/val/test)

Re-running resumes: finished files are recorded in <out>/markers/.
"""

import argparse
import shutil
import subprocess
import urllib.request
from pathlib import Path

BASE_URL = "https://www.campar.in.tum.de/public_datasets/2025_cvpr_oezsoy/MM-OR"

# Annotation archives reScrub needs. take_jsons maps frames to images; the sterility-breach
# labels are the ground truth for evaluating the final timestamped analysis.
ANNOTATIONS = ["take_jsons.zip", "take_timestamp_to_sterility_breach.zip", "take_tracks.zip"]

PROFILES = {
    # One surgery per split: the quickest end-to-end run that still keeps train, val and test apart.
    "tiny": {"train": ["005_TKA"], "val": ["009_TKA"], "test": ["038_TKA"]},
    # The smallest surgeries (~41 GB zipped): enough to run and check the whole flow.
    "small": {"train": ["005_TKA", "010_PKA"], "val": ["009_TKA"], "test": ["038_TKA"]},
    "full": {
        "train": ["001_PKA", "003_TKA", "005_TKA", "006_PKA", "008_PKA", "010_PKA", "012_PKA", "035_PKA", "037_TKA"],
        "val": ["002_PKA", "007_TKA", "009_TKA"],
        "test": ["004_PKA", "011_TKA", "036_PKA", "038_TKA"],
    },
}
SHORT_CLIPS = ["013_PKA", "014_PKA", "015-018_PKA", "019-022_PKA", "023-032_PKA", "033_PKA"]

# Inside each take folder, everything not matching these is deleted by --prune.
KEEP_PREFIXES = ("colorimage", "simstation", "segmentation_export_", "relation_labels",
                 "timestamp_to_pcd_and_frames_list", "timestamps")


def remote_size(url: str) -> int | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
            return int(r.headers.get("Content-Length") or 0) or None
    except Exception:
        return None


def prune_take(folder: Path) -> int:
    freed = 0
    for child in folder.iterdir():
        if child.name.startswith(KEEP_PREFIXES):
            continue
        if child.is_dir():
            size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
            shutil.rmtree(child)
        else:
            size = child.stat().st_size
            child.unlink()
        freed += size
    return freed


def fetch(name: str, out: Path, markers: Path, prune: bool, dry_run: bool) -> None:
    marker = markers / f"{name}.downloaded"
    if marker.exists():
        print(f"{name}: already done")
        return
    url = f"{BASE_URL}/{name}"
    size = remote_size(url)
    free = shutil.disk_usage(out).free
    print(f"{name}: {size / 1e9:.1f} GB" if size else f"{name}: size unknown", f"(free {free / 1e9:.0f} GB)")
    if dry_run:
        return
    # zip + extracted copy must fit at the same time
    if size and size * 2.2 > free:
        raise SystemExit(f"Not enough disk for {name}: need ~{size * 2.2 / 1e9:.0f} GB, have {free / 1e9:.0f} GB. "
                         "Free some space, use a bigger disk, or use a smaller --profile.")
    zip_path = out / name
    subprocess.run(["wget", "-c", "-q", "--show-progress", url, "-O", str(zip_path)], check=True)
    data = out / "MM-OR_data"
    subprocess.run(["unzip", "-q", "-o", str(zip_path), "-d", str(data)], check=True)
    zip_path.unlink()
    # The zips contain an extra MM-OR_processed/ level; flatten it (a rename, no copying).
    nested = data / "MM-OR_processed"
    if nested.is_dir():
        for child in nested.iterdir():
            dest = data / child.name
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            child.rename(dest)
        nested.rmdir()
    if prune and not name.startswith("take_"):
        folder = data / name.removesuffix(".zip")
        if folder.is_dir():
            print(f"  pruned {prune_take(folder) / 1e9:.1f} GB of unused modalities")
    marker.touch()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="folder that will contain MM-OR_data/")
    ap.add_argument("--profile", choices=PROFILES, default="small")
    ap.add_argument("--splits", default="train,val,test", help="which splits to download")
    ap.add_argument("--short-clips", action="store_true", help="also download the short clips (extra training data)")
    ap.add_argument("--takes", help="download exactly these take zips instead of a profile, e.g. 013_PKA,038_TKA")
    ap.add_argument("--no-prune", action="store_true", help="keep depth, point clouds and other unused modalities")
    ap.add_argument("--dry-run", action="store_true", help="only print sizes")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    markers = args.out / "markers"
    markers.mkdir(exist_ok=True)
    if args.takes:
        takes = [t.strip() for t in args.takes.split(",")]
    else:
        takes = [t for s in args.splits.split(",") for t in PROFILES[args.profile][s.strip()]]
    if args.short_clips:
        takes += SHORT_CLIPS
    for name in ANNOTATIONS + [f"{t}.zip" for t in takes]:
        fetch(name, args.out, markers, not args.no_prune, args.dry_run)
    print("MM-OR data ready in", args.out / "MM-OR_data")


if __name__ == "__main__":
    main()
