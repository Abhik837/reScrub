"""Tune the breach rules on saved pipeline outputs, then report them once on held-out surgeries.

The vision pipeline (tracking, hands, surfaces, depth) is the slow part; the breach rules run
on its saved contact rows in seconds. So the rules are tuned by re-scoring the same outputs with
many rule settings, instead of re-running video:

1. tune on the validation surgeries (`--tune-results`, from `run_all.sh` with EVAL_SPLITS="val test");
2. report the chosen settings on the test surgeries (`--report-results`), which tuning never saw;
3. install them to MODELS_DIR/trained/breach_params.json, where the worker reads them.

Settings are ranked by F-beta of findings vs MM-OR's labeled breaches (beta 2 by default:
finding a breach matters more than one extra flag, because an instructor reviews every flag).

    python -m training.tune_breaches --mmor /data/MM-OR_data \\
        --tune-results /data/eval_results/val  --tune-videos /data/eval_videos/val \\
        --report-results /data/eval_results/test --report-videos /data/eval_videos/test
"""

import argparse
import itertools
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from rescrub.analysis.breaches import PARAMS_FILE, Params, analyze, load_jsonl

from .evaluate_breaches import gt_events, match
from .mmor import resolve_root

# Every combination is tried. The contact re-checks can only tighten the pipeline's own
# thresholds (8 px, 0.08 depth, 400 px/s), so tuned rules also work on the worker's stored rows.
GRID = {
    "contact_px": [None, 4.0, 0.0],
    "max_depth_gap": [None, 0.05, 0.03],
    "low_fps_min_frames": [1, 2, 3],
    "repeat_window_sec": [0, 30, 60],
    "scrubbed_nonsterile_findings": [True, False],
    "unscrubbed_patient_is_breach": [True, False],
    "chain_window_sec": [10, 20],
}


@dataclass
class Case:
    name: str
    rows: list
    people: dict
    labels: dict
    session_id: str
    events: list


@dataclass
class Score:
    findings: int = 0
    matched: int = 0
    breaches: int = 0
    found: int = 0

    @property
    def precision(self) -> float:
        return self.matched / self.findings if self.findings else 0.0

    @property
    def recall(self) -> float:
        return self.found / self.breaches if self.breaches else 0.0

    def fbeta(self, beta: float) -> float:
        p, r = self.precision, self.recall
        return (1 + beta**2) * p * r / (beta**2 * p + r) if p + r else 0.0

    def as_dict(self, beta: float) -> dict:
        return {"findings": self.findings, "matched_findings": self.matched, "breaches": self.breaches,
                "found_breaches": self.found, "precision": round(self.precision, 4),
                "recall": round(self.recall, 4), f"f{beta:g}": round(self.fbeta(beta), 4)}


def load_cases(results: Path, videos: Path, mmor: Path, gt_merge_gap: float = 10.0) -> list[Case]:
    """Every <results>/<video>/ pipeline output that has a labeled MM-OR take next to it."""
    root = resolve_root(mmor)
    cases = []
    for out in sorted(p.parent for p in results.glob("*/summary.json")):
        meta_path = videos / f"{out.name}.frames.json"
        if not meta_path.exists() or not (out / "proximity_events.jsonl").exists():
            print(f"  {out.name}: no video metadata or contact rows, skipping")
            continue
        meta = json.loads(meta_path.read_text())
        gt_path = root / "take_timestamp_to_sterility_breach" / f"{meta['take']}.json"
        if not gt_path.exists():
            print(f"  {out.name}: no breach labels for {meta['take']}, skipping")
            continue
        label_to_sec = {int(k): v for k, v in meta["label_to_sec"].items()}
        events = gt_events(json.loads(gt_path.read_text()), label_to_sec, gt_merge_gap)
        rows, people, labels, sid = load_jsonl(out)
        cases.append(Case(out.name, compact(rows), people, labels, sid, events))
        print(f"  {out.name}: {sum(r['candidate_contact'] for r in rows)} contact rows, {len(events)} labeled breaches")
    return cases


def compact(rows: list[dict]) -> list[dict]:
    """Contact rows, plus one other row per timestamp so the frame clock (frame_interval) is unchanged.

    The rules only read contact rows; dropping the rest makes each of the many re-scorings fast.
    """
    contacts = [r for r in rows if r["candidate_contact"]]
    seen = {round(float(r["video_sec"]), 4) for r in contacts}
    clock = []
    for r in rows:
        t = round(float(r["video_sec"]), 4)
        if t not in seen:
            seen.add(t)
            clock.append(r)
    return contacts + clock


def evaluate(cases: list[Case], params: Params, tolerance: float) -> Score:
    s = Score()
    for c in cases:
        findings = analyze(c.rows, c.people, c.labels, c.session_id, params)
        matched, found, _ = match(findings, c.events, tolerance)
        s.findings += len(findings)
        s.matched += matched
        s.breaches += len(c.events)
        s.found += found
    return s


def candidates(grid: dict) -> list[Params]:
    keys = list(grid)
    return [replace(Params(), **dict(zip(keys, values))) for values in itertools.product(*grid.values())]


def search(cases: list[Case], grid: dict, tolerance: float, beta: float) -> list[tuple[Params, Score]]:
    """All settings, best first: highest F-beta, then higher recall, then fewer findings."""
    scored = [(p, evaluate(cases, p, tolerance)) for p in candidates(grid)]
    return sorted(scored, key=lambda ps: (-ps[1].fbeta(beta), -ps[1].recall, ps[1].findings))


def _changed(p: Params) -> dict:
    default = asdict(Params())
    return {k: v for k, v in asdict(p).items() if v != default[k]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmor", type=Path, required=True, help="MM-OR_data (with take_timestamp_to_sterility_breach/)")
    ap.add_argument("--tune-results", type=Path, default=Path("/data/eval_results/val"))
    ap.add_argument("--tune-videos", type=Path, default=Path("/data/eval_videos/val"))
    ap.add_argument("--report-results", type=Path, default=Path("/data/eval_results/test"))
    ap.add_argument("--report-videos", type=Path, default=Path("/data/eval_videos/test"))
    ap.add_argument("--tolerance", type=float, default=3.0, help="seconds of slack (MM-OR runs at 1 frame/s)")
    ap.add_argument("--beta", type=float, default=2.0, help="F-beta: >1 weighs found breaches over extra flags")
    ap.add_argument("--out", type=Path, help=f"where to write the rules (default: MODELS_DIR/trained/{PARAMS_FILE})")
    ap.add_argument("--no-install", action="store_true", help="only print the result")
    args = ap.parse_args()

    print(f"Tuning on {args.tune_results}")
    tune = load_cases(args.tune_results, args.tune_videos, args.mmor)
    if not any(c.events for c in tune):
        raise SystemExit("No labeled validation surgeries to tune on. Run run_all.sh with EVAL_SPLITS=\"val test\".")
    n = len(candidates(GRID))
    started = time.monotonic()
    ranked = search(tune, GRID, args.tolerance, args.beta)
    print(f"Tried {n} settings in {time.monotonic() - started:.0f}s. Best on validation:")
    default_tune = evaluate(tune, Params(), args.tolerance)
    print(f"  defaults: {default_tune.as_dict(args.beta)}")
    for p, s in ranked[:5]:
        print(f"  {s.as_dict(args.beta)}  {_changed(p)}")
    best, best_score = ranked[0]

    report = {}
    if args.report_results.exists():
        print(f"\nHeld-out report on {args.report_results} (never used for tuning):")
        held = load_cases(args.report_results, args.report_videos, args.mmor)
        if held:
            before, after = evaluate(held, Params(), args.tolerance), evaluate(held, best, args.tolerance)
            report = {"defaults": before.as_dict(args.beta), "tuned": after.as_dict(args.beta)}
            print(f"  defaults: {report['defaults']}\n  tuned:    {report['tuned']}")

    result = {"params": asdict(best), "changed_from_defaults": _changed(best),
              "tuned_on": str(args.tune_results), "validation": best_score.as_dict(args.beta),
              "validation_defaults": default_tune.as_dict(args.beta), "held_out": report,
              "tolerance_sec": args.tolerance, "beta": args.beta}
    if args.no_install:
        print(json.dumps(result, indent=2))
        return
    if best_score.fbeta(args.beta) <= default_tune.fbeta(args.beta):
        print("\nThe defaults are already the best on validation; nothing installed.")
        return
    out = args.out
    if out is None:
        from rescrub.settings import get_settings

        out = get_settings().models_dir / "trained" / PARAMS_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"\nInstalled tuned breach rules -> {out}")


if __name__ == "__main__":
    main()
