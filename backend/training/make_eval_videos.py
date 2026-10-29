"""Turn held-out MM-OR surgeries into single-camera MP4s for end-to-end evaluation.

reScrub's input is one recording from one angled camera, so each test take
becomes one MP4 per chosen camera, on MM-OR's real clock: images are captured
once per second and take_jsons/<take>.json gives each frame's
`original_timestamp` in seconds. Missing images repeat the previous frame so
video time always equals recording time.

Next to every video, <name>.frames.json records how to put MM-OR labels on the
video clock. The sterility-breach labels and scene graphs are keyed by
*labeled* frame index (position in timestamp_to_pcd_and_frames_list.json):

    {"take": "038_TKA", "source": "simstation", "camera": 0, "fps": 1.0, "t0": 197,
     "duration_sec": 2876.0, "label_to_sec": {"0": 0.0, "1": 6.0, ...}}

    python -m training.make_eval_videos --mmor /data/MM-OR_data --out /data/eval_videos
"""

import argparse
import json
import subprocess
from pathlib import Path

import cv2

from .mmor import MMOR_SPLITS, MMOR_TAKE_TO_FOLDER, resolve_root

DEFAULT_CAMERA = {"simstation": "0", "azure": "4"}  # azure 4 is the angled side view


def pick_source(root: Path, take: str) -> str:
    dense = json.loads((root / "take_jsons" / f"{take}.json").read_text())["timestamps"].values()
    return "simstation" if any(i.get("simstation") for i in dense) else "azure"


def image_path(take_dir: Path, source: str, camera: int, image_id: str) -> Path:
    if source == "azure":
        return take_dir / "colorimage" / f"camera0{camera}_colorimage-{image_id}.jpg"
    return take_dir / "simstation" / f"camera0{camera}_{image_id}.jpg"


def labeled_frames(take_dir: Path, take: str) -> list:
    for name in (f"timestamp_to_pcd_and_frames_list_{take}.json", "timestamp_to_pcd_and_frames_list.json"):
        if (take_dir / name).exists():
            return json.loads((take_dir / name).read_text())
    return []


def write_video(root: Path, take: str, source: str, camera: int, out: Path, fps: float, max_side: int) -> dict:
    take_dir = root / MMOR_TAKE_TO_FOLDER.get(take, take)
    dense = json.loads((root / "take_jsons" / f"{take}.json").read_text())["timestamps"]
    by_time: dict[int, str] = {}
    for info in dense.values():
        if info.get(source) and info.get("original_timestamp") is not None:
            by_time[int(info["original_timestamp"])] = info[source]
    if not by_time:
        raise FileNotFoundError(f"{take} has no {source} frames")
    t0, t_end = min(by_time), max(by_time)
    name = f"{take}_{source}{camera}"
    video = out / f"{name}.mp4"
    proc, size, last, written = None, None, None, 0
    n_frames = int((t_end - t0) * fps) + 1
    for k in range(n_frames):
        t = t0 + k / fps
        img_id = by_time.get(int(t)) if abs(t - round(t)) < 1e-6 else None
        img = cv2.imread(str(image_path(take_dir, source, camera, img_id))) if img_id else None
        if img is None:
            img = last  # hold the previous frame so the video clock stays exact
        if img is None:
            continue
        if size is None:
            h, w = img.shape[:2]
            s = min(1.0, max_side / max(h, w))
            size = (int(w * s) // 2 * 2, int(h * s) // 2 * 2)
            proc = subprocess.Popen(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                 f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)],
                stdin=subprocess.PIPE,
            )
            # Frames before the first real image cannot be shown; start the clock there instead.
            t0 = t
        if img.shape[1::-1] != size:
            img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        last = img
        proc.stdin.write(img.tobytes())
        written += 1
    if proc is None:
        raise FileNotFoundError(f"no {source} camera {camera} images for {take}")
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")

    label_to_sec = {}
    for i, entry in enumerate(labeled_frames(take_dir, take)):  # [key, ids] (some takes add a 3rd field)
        ot = entry[1].get("original_timestamp")
        if ot is not None and t0 <= ot <= t_end:
            label_to_sec[str(i)] = round(float(ot) - t0, 3)
    meta = {"take": take, "source": source, "camera": camera, "fps": fps, "t0": t0, "video": video.name,
            "frames": written, "duration_sec": written / fps, "label_to_sec": label_to_sec}
    (out / f"{name}.frames.json").write_text(json.dumps(meta))
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmor", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", default="test", choices=["test", "val"], help="val for tuning, test for the final score")
    ap.add_argument("--takes", help="comma separated takes (default: every take of --split that is on disk)")
    ap.add_argument("--source", default="auto", choices=["auto", "simstation", "azure"],
                    help="auto = simstation if the take has it, else azure (takes differ)")
    ap.add_argument("--cameras", default="auto",
                    help="camera numbers (simstation: 0,2,3; azure: 1,4,5); auto = simstation 0 / azure 4")
    ap.add_argument("--fps", type=float, default=1.0, help="MM-OR captures 1 frame per second")
    ap.add_argument("--max-side", type=int, default=1280)
    args = ap.parse_args()

    root = resolve_root(args.mmor)
    args.out.mkdir(parents=True, exist_ok=True)
    takes = args.takes.split(",") if args.takes else MMOR_SPLITS[args.split]
    for take in takes:
        if not (root / MMOR_TAKE_TO_FOLDER.get(take, take)).exists():
            print(f"{take}: not downloaded, skipping")
            continue
        source = args.source if args.source != "auto" else pick_source(root, take)
        cams = DEFAULT_CAMERA[source] if args.cameras == "auto" else args.cameras
        for cam in (int(c) for c in cams.split(",")):
            meta = write_video(root, take, source, cam, args.out, args.fps, args.max_side)
            print(f"{meta['video']}: {meta['frames']} frames ({meta['duration_sec'] / 60:.1f} min), "
                  f"{len(meta['label_to_sec'])} labeled frames on the video clock")


if __name__ == "__main__":
    main()
