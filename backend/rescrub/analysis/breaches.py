"""Rule-based contamination analysis over the tracking data -> timestamped findings.

Reads the per-frame proximity features (from the database or the CLI's JSON lines), groups
frames into contact events and applies sterile-technique rules:

- unscrubbed person contacts a sterile surface             -> finding
- scrubbed person contacts a nonsterile surface            -> finding
- ...and then contacts something sterile with the same hand -> one chained finding
  ("glove touches side table, then forceps"), the classic contamination path

Every finding uses the website's `Finding` shape (web/lib/types.ts) with
`timestampSec`/`endSec` in seconds from the start of the recording.

A long recording can produce more findings than the website shows (MAX_FINDINGS). The
strongest ones are kept across the whole recording, then sorted by time, so breaches late in
a surgery are not crowded out by weak early ones. The thresholds live in `Params`; tuned values
(training/tune_breaches.py) are read from MODELS_DIR/trained/breach_params.json when present.

    python -m rescrub.analysis.breaches --jsonl out/            # CLI output folder
    python -m rescrub.analysis.breaches --session <uuid> [--save] # from the database
"""

import argparse
import json
import logging
from collections import Counter
from dataclasses import dataclass, field, fields
from pathlib import Path

MAX_FINDINGS = 200
MAX_EVIDENCE = 12
PARAMS_FILE = "breach_params.json"  # in MODELS_DIR/trained, written by training/tune_breaches.py

log = logging.getLogger(__name__)

PART_NAMES = {
    "wrist": "wrist", "elbow": "forearm", "hand_wrist": "hand", "thumb_tip": "thumb", "index_tip": "index finger",
    "middle_tip": "middle finger", "ring_tip": "ring finger", "pinky_tip": "little finger",
}


@dataclass
class Params:
    merge_gap_sec: float = 0.75   # contacts closer than this are one event
    min_frames: int = 2           # ignore single-frame flickers (normal frame rates)
    low_fps_min_frames: int = 1   # the same at <= 2 fps, where one frame already spans most of a second
    single_frame_needs_inside: bool = True  # at low fps, a 1-frame contact counts only inside the surface outline
    # Stricter re-checks of the pipeline's contact flag (None keeps the flag as recorded). They can only
    # tighten it: rows the pipeline did not flag are never turned into contacts.
    contact_px: float | None = None
    max_depth_gap: float | None = None
    max_speed_px_s: float | None = None
    chain_window_sec: float = 20  # nonsterile contact followed by sterile contact within this -> chained finding
    # MM-OR labels unscrubbed staff touching the patient as a breach; scrubbed staff work on the patient.
    unscrubbed_patient_is_breach: bool = True
    scrubbed_nonsterile_findings: bool = True  # a scrubbed hand on a nonsterile surface, without a chain
    repeat_window_sec: float = 30  # the same contact again within this -> one finding with a longer span
    max_repeat_span_sec: float = 120  # ...but one finding never spans more than this
    max_findings: int = MAX_FINDINGS


def load_params(path: Path | None = None) -> Params:
    """Tuned rules from `path` (default MODELS_DIR/trained/breach_params.json), else the defaults."""
    if path is None:
        from ..settings import get_settings

        s = get_settings()
        path = s.breach_params_file or s.models_dir / "trained" / PARAMS_FILE
    path = Path(path)
    if not path.exists():
        return Params()
    raw = json.loads(path.read_text())
    raw = raw.get("params", raw)
    known = {f.name for f in fields(Params)}
    unknown = sorted(set(raw) - known)
    if unknown:
        log.warning("%s: ignoring unknown breach settings %s", path, ", ".join(unknown))
    params = Params(**{k: v for k, v in raw.items() if k in known})
    log.info("Breach rules from %s", path)
    return params


@dataclass
class ContactEvent:
    person: str
    person_designation: str
    side: str            # "left" | "right" | ""
    surface_id: str
    surface_label: str
    designation: str     # of the surface
    start: float
    end: float
    frames: int = 0
    inside_frames: int = 0
    depth_gaps: list = field(default_factory=list)
    parts: set = field(default_factory=set)
    roles: Counter = field(default_factory=Counter)  # the person's role in each contact frame

    @property
    def place(self) -> tuple[str, str]:
        """The kind of surface (designation, label). Surface IDs can change between keyframes while
        the person keeps touching the same drape or patient, so findings are grouped by this."""
        return self.designation, self.surface_label

    @property
    def surface_phrase(self) -> str:
        """'the patient', or 'the Side table (nonsterile)'."""
        if self.surface_label.lower() == self.designation:
            return f"the {self.designation}"
        return f"the {self.surface_label} ({self.designation})"

    @property
    def hand(self) -> str:
        return {"both": "hands", "": "hand"}.get(self.side, f"{self.side} hand")


def _side(part: str) -> str:
    return {"l": "left", "r": "right"}.get(part.split("_", 1)[0], "")


def frame_interval(rows: list[dict]) -> float:
    """Typical time between analyzed frames (e.g. 0.04 s for 25 fps video, 1 s for MM-OR)."""
    times = sorted({round(float(r["video_sec"]), 4) for r in rows})
    if len(times) < 2:
        return 0.0
    diffs = sorted(b - a for a, b in zip(times, times[1:]))
    return diffs[len(diffs) // 2]


def is_contact(r: dict, p: Params) -> bool:
    """The pipeline's contact flag, optionally re-checked with stricter thresholds."""
    if not r["candidate_contact"]:
        return False
    if p.contact_px is not None and r.get("pixel_dist") is not None and r["pixel_dist"] > p.contact_px:
        return False
    if p.max_depth_gap is not None and r.get("depth_gap") is not None and abs(r["depth_gap"]) > p.max_depth_gap:
        return False
    return not (p.max_speed_px_s is not None and r.get("speed_px_s") is not None
                and r["speed_px_s"] > p.max_speed_px_s)


def group_events(rows: list[dict], people: dict[str, str], labels: dict[str, str], p: Params,
                 frame_dt: float | None = None) -> list[ContactEvent]:
    """Merge candidate-contact frames into events per (person, hand, surface).

    Gaps and minimum length scale with the frame rate, so 1-frame-per-second
    recordings are handled like normal video. `frame_dt` is the time between analyzed
    frames; without it, it is measured from `rows`, which then must include non-contact
    rows (contacts alone can be sparse and make a 30 fps video look like 1 fps).
    """
    dt = frame_dt or frame_interval(rows)
    merge_gap = max(p.merge_gap_sec, 1.5 * dt)
    low_fps = dt >= 0.5
    min_frames = p.low_fps_min_frames if low_fps else p.min_frames
    open_events: dict[tuple, ContactEvent] = {}
    done: list[ContactEvent] = []
    for r in sorted((r for r in rows if is_contact(r, p)), key=lambda r: r["video_sec"]):
        label = labels.get(r["surface_id"], r["surface_id"])
        key = (r["person_label"], _side(r["part"]), r["designation"], label)
        t = float(r["video_sec"])
        ev = open_events.get(key)
        if ev and t - ev.end > merge_gap:
            done.append(ev)
            ev = None
        if ev is None:
            ev = ContactEvent(r["person_label"], people.get(r["person_label"], "sterile"), key[1], r["surface_id"],
                              label, r["designation"], t, t)
            open_events[key] = ev
        if t > ev.end or ev.frames == 0:
            ev.frames += 1
            ev.inside_frames += bool(r.get("inside_mask"))
        ev.end = t
        ev.parts.add(r["part"].split("_", 1)[1] if "_" in r["part"] else r["part"])
        if r.get("depth_gap") is not None:
            ev.depth_gaps.append(float(r["depth_gap"]))
        if r.get("person_designation"):
            ev.roles[r["person_designation"]] += 1
    done.extend(open_events.values())
    for e in done:
        # The role shown in the labeled video while the contact happened. Rows from before this was
        # recorded have none, and keep the person's final role.
        if e.roles:
            e.person_designation = e.roles.most_common(1)[0][0]

    def keep(e: ContactEvent) -> bool:
        if e.frames < min_frames:
            return False
        if low_fps and e.frames == 1 and p.single_frame_needs_inside:
            return e.inside_frames >= 1
        return True

    return sorted((e for e in done if keep(e)), key=lambda e: e.start)


def merge_hands(events: list[ContactEvent], gap: float) -> list[ContactEvent]:
    """Left- and right-hand events of one person on one surface that overlap in time become one."""
    out: list[ContactEvent] = []
    by_place: dict[tuple, list[ContactEvent]] = {}  # (person, surface) -> merged events, in order
    for e in sorted(events, key=lambda e: e.start):
        same_place = by_place.setdefault((e.person, e.place), [])
        twin = next((o for o in same_place if o.side != e.side and e.start <= o.end + gap), None)
        if twin is None:
            merged = ContactEvent(**{**e.__dict__, "parts": set(e.parts), "depth_gaps": list(e.depth_gaps)})
            out.append(merged)
            same_place.append(merged)
            continue
        twin.side = "both" if twin.side != e.side else twin.side
        twin.end = max(twin.end, e.end)
        twin.frames += e.frames
        twin.inside_frames += e.inside_frames
        twin.depth_gaps += e.depth_gaps
        twin.parts |= e.parts
        twin.roles += e.roles
    return out


def _uncertainty(events: list[ContactEvent]) -> dict:
    has_depth = all(e.depth_gaps for e in events)
    inside = sum(e.inside_frames for e in events) / max(1, sum(e.frames for e in events))
    if has_depth and inside >= 0.6:
        return {"level": "low", "notes": "The hand is inside the surface outline at a similar depth for most frames."}
    if has_depth or inside >= 0.6:
        return {"level": "medium", "notes": "Contact is likely but a single camera cannot fully separate touching "
                                            "from hovering."}
    return {"level": "high", "notes": "Based on image position only (no depth). The hand may be hovering in "
                                      "front of the surface."}


def _step(e: ContactEvent, text: str) -> dict:
    return {"label": e.surface_label, "designation": e.designation if e.designation in ("sterile", "nonsterile")
            else "unknown", "timestampSec": round(e.start, 2), "observation": text}


def _parts(e: ContactEvent) -> str:
    return ", ".join(sorted({PART_NAMES.get(x, x) for x in e.parts}))


def analyze(rows: list[dict], people: dict[str, str], labels: dict[str, str], session_id: str,
            p: Params | None = None, frame_dt: float | None = None) -> list[dict]:
    p = p or Params()
    frame_dt = frame_dt or frame_interval(rows)
    events = group_events(rows, people, labels, p, frame_dt)
    merge_gap = max(p.merge_gap_sec, 1.5 * frame_dt)
    findings: list[dict] = []
    used: set[int] = set()

    def add(rule: str, key: tuple, start: float, end: float, title: str, objects: list[str], description: str,
            reason: str, evidence: list[dict], unc_events: list[ContactEvent]) -> None:
        unc = _uncertainty(unc_events)
        findings.append({
            "sessionId": session_id, "eventId": "", "timestampSec": round(max(0.0, start), 2),
            "endSec": round(end, 2), "title": title, "objects": objects, "description": description,
            "reasonForReview": reason, "evidence": evidence, "uncertainty": unc,
            "reviewStatus": "needs_review",
            "_key": (rule, *key), "_score": _strength(rule, unc["level"], end - start), "_repeats": 0,
        })

    # 1) Scrubbed hand: nonsterile contact, then sterile contact with the same hand.
    sterile_by_hand: dict[tuple, list[int]] = {}  # (person, side) -> indexes of sterile contacts, by start
    for j, b in enumerate(events):
        if b.designation == "sterile":
            sterile_by_hand.setdefault((b.person, b.side), []).append(j)
    for i, a in enumerate(events):
        if a.person_designation != "sterile" or a.designation != "nonsterile":
            continue
        nxt = None
        for j in sterile_by_hand.get((a.person, a.side), []):
            gap = events[j].start - a.end
            if j <= i or gap < 0:
                continue
            if gap <= p.chain_window_sec:
                nxt = j
            break  # events are sorted by start: later ones are even further away
        if nxt is None:
            continue
        b = events[nxt]
        used.update({i, nxt})
        add("chain", (a.person, a.side, a.place, b.place), a.start, b.end,
            f"{a.person}'s {a.hand} touches {a.surface_label}, then {b.surface_label}",
            [a.surface_label, f"{a.person} {a.hand}", b.surface_label],
            f"{a.person} ({_parts(a)}) contacts {a.surface_phrase} at {a.start:.1f}s, then "
            f"{b.surface_phrase} at {b.start:.1f}s with the same hand.",
            "A sterile glove appears to touch a nonsterile surface and then a sterile one; the glove would carry "
            "contamination onto the sterile field.",
            [_step(a, f"{a.person}'s {a.hand} contacts {a.surface_label} for {a.end - a.start:.1f}s."),
             {"label": f"{a.person} {a.hand}", "designation": "sterile", "timestampSec": round(a.end, 2),
              "observation": "Hand leaves the nonsterile surface."},
             _step(b, f"Same hand contacts {b.surface_label}.")],
            [a, b])

    # 2) Single contacts that break asepsis on their own (both hands on one surface = one finding).
    for e in merge_hands([e for i, e in enumerate(events) if i not in used], merge_gap):
        breach_targets = ("sterile", "patient") if p.unscrubbed_patient_is_breach else ("sterile",)
        if e.person_designation == "nonsterile" and e.designation in breach_targets:
            add("unscrubbed", (e.person, e.place), e.start, e.end,
                f"Unscrubbed {e.person} touches {e.surface_label}",
                [f"{e.person} (unscrubbed)", e.surface_label],
                f"{e.person}, who is not scrubbed, contacts {e.surface_phrase} ({_parts(e)}).",
                "Only scrubbed staff may touch the sterile field or the prepped patient; this may need to be "
                "re-prepped or replaced.",
                [{"label": f"{e.person} {e.hand}", "designation": "nonsterile", "timestampSec": round(e.start, 2),
                  "observation": f"Unscrubbed hand reaches {e.surface_phrase}."},
                 _step(e, f"Contact for {e.end - e.start:.1f}s.")], [e])
        elif e.person_designation == "sterile" and e.designation == "nonsterile" and p.scrubbed_nonsterile_findings:
            verb = "touch" if e.side == "both" else "touches"
            add("scrubbed", (e.person, e.side, e.place), e.start, e.end,
                f"{e.person}'s {e.hand} {verb} {e.surface_label}",
                [f"{e.person} {e.hand}", e.surface_label],
                f"{e.person} ({_parts(e)}) contacts {e.surface_phrase}.",
                "A scrubbed person's glove or sleeve is no longer sterile after this contact; it should be changed "
                "before touching the sterile field.",
                [_step(e, f"{e.person}'s {e.hand} contacts {e.surface_label} for {e.end - e.start:.1f}s.")],
                [e])

    findings = merge_repeats(findings, p)
    # Keep the strongest findings across the whole recording (the website shows at most
    # MAX_FINDINGS, web/lib/validate.ts), then put them back in time order.
    cap = min(p.max_findings, MAX_FINDINGS)
    findings = sorted(findings, key=lambda f: (tuple(-x for x in f["_score"]), f["timestampSec"]))[:cap]
    findings.sort(key=lambda f: (f["timestampSec"], f["endSec"]))
    for n, f in enumerate(findings, 1):
        f["evidence"] = f["evidence"][:MAX_EVIDENCE]
        f["eventId"] = f"evt-{n}"
        for k in ("_key", "_score", "_repeats"):
            del f[k]
    return findings


RULE_RANK = {"unscrubbed": 1, "chain": 1, "scrubbed": 0}  # contamination of the sterile field ranks first
UNCERTAINTY_RANK = {"low": 2, "medium": 1, "high": 0}


def _strength(rule: str, uncertainty: str, duration: float) -> tuple:
    """Compared in order: rule, then uncertainty, then contact length. A weaker rule never outranks a stronger
    one, however long or certain it is."""
    return RULE_RANK[rule], UNCERTAINTY_RANK[uncertainty], max(duration, 0.0)


def merge_repeats(findings: list[dict], p: Params) -> list[dict]:
    """The same contact again soon after (same rule, person, hand and surfaces) extends one finding.

    A person resting a hand on a table for minutes is one thing to review, not dozens.
    """
    if p.repeat_window_sec <= 0:
        return findings
    out: list[dict] = []
    last: dict[tuple, dict] = {}
    for f in sorted(findings, key=lambda f: (f["timestampSec"], f["endSec"])):
        prev = last.get(f["_key"])
        if (prev is not None and f["timestampSec"] - prev["endSec"] <= p.repeat_window_sec
                and f["endSec"] - prev["timestampSec"] <= p.max_repeat_span_sec):
            prev["endSec"] = max(prev["endSec"], f["endSec"])
            prev["evidence"] = prev["evidence"] + [
                {**step, "observation": f"Again: {step['observation']}"} for step in f["evidence"][:1]]
            prev["_repeats"] += 1
            if f["uncertainty"]["level"] == "low":
                prev["uncertainty"] = f["uncertainty"]
            # Same rule; ranks by the best uncertainty and the whole span (repeated contact is more likely real).
            prev["_score"] = (prev["_score"][0], max(prev["_score"][1], f["_score"][1]),
                              prev["endSec"] - prev["timestampSec"])
            continue
        f = {**f}
        out.append(f)
        last[f["_key"]] = f
    for f in out:
        if f["_repeats"]:
            n = f["_repeats"] + 1
            f["description"] += (f" The same contact happens {n} times between {f['timestampSec']:.1f}s "
                                 f"and {f['endSec']:.1f}s.")
    return out


# --- loaders ---------------------------------------------------------------

def load_jsonl(out_dir: Path) -> tuple[list[dict], dict[str, str], dict[str, str], str]:
    out_dir = Path(out_dir)
    summary = json.loads((out_dir / "summary.json").read_text())
    people = {p["person_label"]: p.get("designation", "sterile") for p in summary["people"]}
    labels = {}
    for line in (out_dir / "surfaces.jsonl").read_text().splitlines():
        s = json.loads(line)
        labels[s["surface_id"]] = s["label"]
    rows = [json.loads(line) for line in (out_dir / "proximity_events.jsonl").read_text().splitlines()]
    return rows, people, labels, summary["session_id"]


def load_db(pool, session_id: str) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    from .. import db

    people = {p["person_label"]: p["designation"] for p in db.list_people(pool, session_id)}
    labels = {s["surface_id"]: s["label"] for s in db.list_surfaces(pool, session_id)}
    rows = db.list_proximity(pool, session_id, candidate_only=True, start=None, end=None, limit=2_000_000)
    return rows, people, labels


def session_frame_dt(pool, session_id: str) -> float | None:
    """Seconds between analyzed frames, from the video's frame rate and FRAME_STRIDE.

    The worker loads only contact rows, so the spacing can't be measured from them.
    """
    from .. import db
    from ..settings import get_settings

    fps = (db.get_session(pool, session_id) or {}).get("fps")
    return max(1, get_settings().frame_stride) / fps if fps else None


def analyze_session(pool, session_id: str, save: bool = True, params: Params | None = None) -> list[dict]:
    from .. import db

    rows, people, labels = load_db(pool, session_id)
    findings = analyze(rows, people, labels, session_id, params or load_params(), session_frame_dt(pool, session_id))
    if save:
        db.replace_findings(pool, session_id, findings)
    return findings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--jsonl", type=Path, help="output folder of `python -m rescrub.pipeline.run`")
    src.add_argument("--session", help="session id in the database")
    ap.add_argument("--save", action="store_true", help="write findings to the database (with --session)")
    ap.add_argument("--out", type=Path, help="also write findings JSON here")
    ap.add_argument("--params", type=Path, help="breach rules JSON (default: MODELS_DIR/trained/breach_params.json)")
    args = ap.parse_args()
    params = load_params(args.params)

    if args.jsonl:
        rows, people, labels, sid = load_jsonl(args.jsonl)
        findings = analyze(rows, people, labels, sid, params)
    else:
        from .. import db
        from ..settings import get_settings

        pool = db.connect(get_settings().database_url)
        findings = analyze_session(pool, args.session, save=args.save, params=params)
    text = json.dumps(findings, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
