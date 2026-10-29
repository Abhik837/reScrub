"""Breach-rule tuning (training/tune_breaches.py) on small synthetic pipeline outputs."""

import json
import sys

from rescrub.analysis.breaches import Params, load_params
from training import tune_breaches as tb


def row(t, person, part, surface, designation, contact=True, inside=True, dist=0.0):
    return {"video_sec": t, "person_label": person, "part": part, "surface_id": surface, "designation": designation,
            "candidate_contact": contact, "inside_mask": inside, "depth_gap": None, "pixel_dist": dist,
            "speed_px_s": None}


PEOPLE = {"Person 1": "sterile", "Person 2": "nonsterile"}
LABELS = {"tray-1": "Instrument tray", "side-table-1": "Side table"}


def surgery() -> tuple[list[dict], list[dict]]:
    """One real breach (Person 2 at the tray, 100-102 s) among many brief side-table touches 6 px away."""
    rows = [row(float(t), "Person 2", "r_wrist", "tray-1", "sterile") for t in (100, 101, 102)]
    for k in range(40):
        rows += [row(float(t), "Person 1", "l_wrist", "side-table-1", "nonsterile", dist=6.0)
                 for t in (k * 7 + 3, k * 7 + 4)]
    rows += [row(float(t), "Person 1", "r_elbow", "tray-1", "sterile", contact=False) for t in range(0, 300)]
    return rows, [{"start": 100.0, "end": 101.0, "breaches": {"circulator touching instrument_table"}}]


def test_compact_keeps_contacts_and_the_frame_clock():
    rows, _ = surgery()
    small = tb.compact(rows)
    assert sum(r["candidate_contact"] for r in small) == sum(r["candidate_contact"] for r in rows)
    assert {r["video_sec"] for r in small} == {r["video_sec"] for r in rows}
    assert len(small) < len(rows)


def test_search_prefers_rules_that_drop_false_alarms():
    rows, events = surgery()
    case = tb.Case("v", tb.compact(rows), PEOPLE, LABELS, "s", events)
    default = tb.evaluate([case], Params(), tolerance=3)
    assert default.found == 1 and default.findings > 1
    grid = {"contact_px": [None, 4.0], "scrubbed_nonsterile_findings": [True, False]}
    best, score = tb.search([case], grid, tolerance=3, beta=2)[0]
    assert score.found == 1 and score.findings == 1 and score.precision == 1.0
    assert best.contact_px == 4.0 or best.scrubbed_nonsterile_findings is False
    assert score.fbeta(2) > default.fbeta(2)


def test_main_tunes_on_val_reports_test_and_installs(tmp_path, monkeypatch, capsys):
    mmor = tmp_path / "MM-OR_data"
    (mmor / "take_timestamp_to_sterility_breach").mkdir(parents=True)
    rows, _ = surgery()
    for split in ("val", "test"):
        out = tmp_path / "results" / split / f"T_{split}_simstation0"
        out.mkdir(parents=True)
        (out / "summary.json").write_text(json.dumps({"session_id": split, "people": [
            {"person_label": k, "designation": v} for k, v in PEOPLE.items()]}))
        (out / "surfaces.jsonl").write_text("\n".join(json.dumps({"surface_id": k, "label": v})
                                                      for k, v in LABELS.items()))
        (out / "proximity_events.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        videos = tmp_path / "videos" / split
        videos.mkdir(parents=True)
        (videos / f"T_{split}_simstation0.frames.json").write_text(json.dumps(
            {"take": f"T_{split}", "duration_sec": 300, "label_to_sec": {"0": 100.0, "1": 101.0, "2": 250.0}}))
        (mmor / "take_timestamp_to_sterility_breach" / f"T_{split}.json").write_text(json.dumps(
            {"0": [["circulator", "instrument_table", "touching"]],
             "1": [["circulator", "instrument_table", "touching"]], "2": []}))
    dest = tmp_path / "trained" / "breach_params.json"
    monkeypatch.setattr(tb, "GRID", {"contact_px": [None, 4.0], "scrubbed_nonsterile_findings": [True, False]})
    monkeypatch.setattr(sys, "argv", [
        "tune_breaches", "--mmor", str(mmor),
        "--tune-results", str(tmp_path / "results/val"), "--tune-videos", str(tmp_path / "videos/val"),
        "--report-results", str(tmp_path / "results/test"), "--report-videos", str(tmp_path / "videos/test"),
        "--out", str(dest)])
    tb.main()
    saved = json.loads(dest.read_text())
    assert saved["validation"]["recall"] == 1.0 and saved["validation"]["precision"] == 1.0
    assert saved["held_out"]["tuned"]["findings"] < saved["held_out"]["defaults"]["findings"]
    assert saved["changed_from_defaults"]
    assert load_params(dest) != Params()
    assert "Installed tuned breach rules" in capsys.readouterr().out
