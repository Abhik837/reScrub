"""Score reScrub's timestamped findings against MM-OR's sterility-breach labels.

For each evaluation video (training/make_eval_videos.py) this:

1. checks the findings' timestamps are usable: inside the video, start <= end,
   evidence steps inside the finding window, sorted;
2. converts MM-OR's breach labels (take_timestamp_to_sterility_breach/<take>.json, keyed by
   labeled-frame index) into time intervals on the same video clock, via <name>.frames.json;
3. matches findings to labeled breaches (overlap within --tolerance seconds) and
   reports precision, recall and onset error in seconds.

    python -m training.evaluate_breaches --mmor /data/MM-OR_data --videos /data/eval_videos --results /data/eval_results
"""

import argparse
import json
from pathlib import Path

from .mmor import resolve_root


def gt_events(breach_json: dict, label_to_sec: dict[int, float], merge_gap_sec: float) -> list[dict]:
    """Breach-labeled frames -> [{"start", "end", "breaches"}] on the video clock.

    MM-OR breach labels map a labeled-frame index to [[subject, object, predicate], ...].
    """
    points = sorted((label_to_sec[int(k)], v) for k, v in breach_json.items() if v and int(k) in label_to_sec)
    events: list[dict] = []
    for t, breaches in points:
        triplets = {f"{b[0]} {b[2]} {b[1]}" for b in breaches}  # "mps holding instrument_table"
        if events and t - events[-1]["end"] <= merge_gap_sec:
            events[-1]["end"] = t
            events[-1]["breaches"] |= triplets
        else:
            events.append({"start": t, "end": t, "breaches": triplets})
    return events


def timestamp_problems(findings: list[dict], duration: float) -> list[str]:
    problems = []
    prev = -1.0
    for f in findings:
        s, e = f["timestampSec"], f.get("endSec", f["timestampSec"])
        if not (0 <= s <= duration + 0.5 and 0 <= e <= duration + 0.5):
            problems.append(f"{f['eventId']}: {s}-{e}s outside the video (0-{duration:.1f}s)")
        if e < s:
            problems.append(f"{f['eventId']}: ends before it starts")
        if s < prev:
            problems.append(f"{f['eventId']}: findings not sorted by time")
        prev = s
        for step in f.get("evidence", []):
            if not (s - 0.05 <= step["timestampSec"] <= e + 0.05):
                problems.append(f"{f['eventId']}: evidence at {step['timestampSec']}s outside {s}-{e}s")
    return problems


def match(findings: list[dict], events: list[dict], tolerance: float) -> tuple[int, int, list[float]]:
    """Returns (#findings matching a labeled breach, #labeled breaches found, onset errors).

    One-to-one: each finding claims at most one labeled breach (the unclaimed overlapping one whose
    start is closest), so a duplicate finding for an already-found breach counts as a false positive.
    """
    claimed: set[int] = set()
    onset: list[float] = []
    for f in sorted(findings, key=lambda f: f["timestampSec"]):
        s, e = f["timestampSec"] - tolerance, f.get("endSec", f["timestampSec"]) + tolerance
        hits = [i for i, g in enumerate(events) if i not in claimed and g["start"] <= e and g["end"] >= s]
        if hits:
            i = min(hits, key=lambda i: abs(f["timestampSec"] - events[i]["start"]))
            claimed.add(i)
            onset.append(abs(f["timestampSec"] - events[i]["start"]))
    return len(claimed), len(claimed), onset


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmor", type=Path, required=True, help="MM-OR_data (with take_timestamp_to_sterility_breach/)")
    ap.add_argument("--videos", type=Path, required=True, help="folder from make_eval_videos")
    ap.add_argument("--results", type=Path, required=True, help="folder with <video>.findings.json")
    ap.add_argument("--tolerance", type=float, default=3.0, help="seconds of slack (MM-OR runs at 1 frame/s)")
    ap.add_argument("--gt-merge-gap", type=float, default=10.0, help="breach labels closer than this are one event")
    args = ap.parse_args()

    totals = {"findings": 0, "matched_findings": 0, "breaches": 0, "found_breaches": 0}
    onsets: list[float] = []
    report = []
    for meta_path in sorted(args.videos.glob("*.frames.json")):
        meta = json.loads(meta_path.read_text())
        name = meta_path.name.removesuffix(".frames.json")
        res = args.results / f"{name}.findings.json"
        if not res.exists():
            print(f"{name}: no findings file, skipping")
            continue
        findings = json.loads(res.read_text())
        label_to_sec = {int(k): v for k, v in meta["label_to_sec"].items()}
        duration = meta["duration_sec"]  # = frames / fps: the last frame is shown for 1/fps
        gt_path = resolve_root(args.mmor) / "take_timestamp_to_sterility_breach" / f"{meta['take']}.json"
        events = gt_events(json.loads(gt_path.read_text()), label_to_sec, args.gt_merge_gap) if gt_path.exists() else []
        problems = timestamp_problems(findings, duration)
        tp_pred, found, onset = match(findings, events, args.tolerance)
        totals["findings"] += len(findings)
        totals["matched_findings"] += tp_pred
        totals["breaches"] += len(events)
        totals["found_breaches"] += found
        onsets += onset
        report.append({"video": name, "duration_sec": duration, "findings": len(findings), "labeled_breaches":
                       len(events), "matched_findings": tp_pred, "found_breaches": found,
                       "timestamp_problems": problems, "has_labels": gt_path.exists(),
                       "labeled": [{"start": round(g["start"], 2), "end": round(g["end"], 2),
                                    "breaches": sorted(g["breaches"])} for g in events]})
        print(f"{name}: {len(findings)} findings, {len(events)} labeled breaches, {found} found, "
              f"{len(problems)} timestamp problems")

    summary = {
        **totals,
        "precision": totals["matched_findings"] / totals["findings"] if totals["findings"] else None,
        "recall": totals["found_breaches"] / totals["breaches"] if totals["breaches"] else None,
        "mean_onset_error_sec": sum(onsets) / len(onsets) if onsets else None,
        "timestamp_problems": sum(len(r["timestamp_problems"]) for r in report),
        "tolerance_sec": args.tolerance,
    }
    (args.results / "evaluation.json").write_text(json.dumps({"summary": summary, "videos": report}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
