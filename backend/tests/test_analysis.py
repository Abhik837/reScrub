import json

import pytest

from rescrub.analysis.breaches import MAX_FINDINGS, Params, analyze, group_events, load_params
from training.evaluate_breaches import gt_events, match, timestamp_problems


def row(t, person, part, surface, designation, contact=True):
    return {"video_sec": t, "person_label": person, "part": part, "surface_id": surface, "designation": designation,
            "candidate_contact": contact, "inside_mask": True, "depth_gap": None}


LABELS = {"side-table-1": "Side table", "tray-1": "Instrument tray", "drape-1": "Sterile drape",
          "patient-1": "Patient"}


def test_frames_merge_into_events_with_exact_times():
    rows = [row(t / 10, "Person 1", "r_wrist", "side-table-1", "nonsterile") for t in range(20, 31)]
    rows += [row(t / 10, "Person 1", "r_index_tip", "side-table-1", "nonsterile") for t in range(20, 31)]
    rows += [row(5.0, "Person 1", "r_wrist", "side-table-1", "nonsterile")]  # single-frame flicker
    ev = group_events(rows, {"Person 1": "sterile"}, LABELS, Params())
    assert len(ev) == 1
    assert (ev[0].start, ev[0].end, ev[0].frames, ev[0].side) == (2.0, 3.0, 11, "right")


def test_chain_nonsterile_then_sterile_same_hand():
    rows = [row(t / 10, "Person 1", "r_wrist", "side-table-1", "nonsterile") for t in range(100, 111)]
    rows += [row(t / 10, "Person 1", "r_wrist", "tray-1", "sterile") for t in range(150, 156)]
    rows += [row(t / 10, "Person 1", "l_wrist", "drape-1", "sterile") for t in range(0, 300)]  # other hand
    f = analyze(rows, {"Person 1": "sterile"}, LABELS, "s1")
    assert len(f) == 1
    assert f[0]["timestampSec"] == 10.0 and f[0]["endSec"] == 15.5
    assert [e["timestampSec"] for e in f[0]["evidence"]] == [10.0, 11.0, 15.0]
    assert [e["designation"] for e in f[0]["evidence"]] == ["nonsterile", "sterile", "sterile"]
    assert timestamp_problems(f, 30.0) == []


def test_unscrubbed_touching_sterile_and_patient_rules():
    rows = [row(t / 10, "Person 2", "l_wrist", "tray-1", "sterile") for t in range(40, 45)]
    rows += [row(t / 10, "Person 1", "r_wrist", "patient-1", "patient") for t in range(0, 50)]
    f = analyze(rows, {"Person 1": "sterile", "Person 2": "nonsterile"}, LABELS, "s1")
    assert [x["title"] for x in f] == ["Unscrubbed Person 2 touches Instrument tray"]
    assert f[0]["eventId"] == "evt-1" and f[0]["timestampSec"] == 4.0 and f[0]["endSec"] == 4.4
    assert f[0]["reviewStatus"] == "needs_review" and f[0]["sessionId"] == "s1"


def test_sterile_contacts_by_scrubbed_staff_are_not_findings():
    rows = [row(t / 10, "Person 1", "r_wrist", "tray-1", "sterile") for t in range(0, 50)]
    assert analyze(rows, {"Person 1": "sterile"}, LABELS, "s1") == []


def test_gt_events_and_matching_on_video_clock():
    labels = {"000010": [["circulator", "instrument_table", "touching"]],
              "000011": [["circulator", "instrument_table", "touching"]],
              "000040": [["nurse", "operating_table", "touching"]], "000020": []}
    label_to_sec = {i: i * 0.5 for i in range(0, 60)}  # labeled frame i at 0.5 s * i
    ev = gt_events(labels, label_to_sec, merge_gap_sec=2)
    assert [(e["start"], e["end"]) for e in ev] == [(5.0, 5.5), (20.0, 20.0)]
    assert ev[0]["breaches"] == {"circulator touching instrument_table"}
    findings = [{"eventId": "evt-1", "timestampSec": 6.0, "endSec": 7.0},
                {"eventId": "evt-2", "timestampSec": 40.0, "endSec": 41.0}]
    tp, found, onset = match(findings, ev, tolerance=2.0)
    assert (tp, found) == (1, 1) and onset == [pytest.approx(1.0)]


def test_matching_is_one_to_one():
    ev = [{"start": 10.0, "end": 11.0}, {"start": 14.0, "end": 15.0}]
    dupes = [{"eventId": "evt-1", "timestampSec": 10.0}, {"eventId": "evt-2", "timestampSec": 10.5}]
    assert match(dupes, ev[:1], tolerance=1.0)[:2] == (1, 1)  # the duplicate is a false positive
    broad = [{"eventId": "evt-1", "timestampSec": 9.0, "endSec": 16.0}]
    assert match(broad, ev, tolerance=0.0)[:2] == (1, 1)  # one finding can't find two breaches


def test_timestamp_problems_detected():
    bad = [{"eventId": "evt-1", "timestampSec": 5, "endSec": 4, "evidence": [{"timestampSec": 9}]},
           {"eventId": "evt-2", "timestampSec": 2, "endSec": 99}]
    probs = timestamp_problems(bad, 30)
    assert any("ends before" in p for p in probs) and any("outside 5-4" in p for p in probs)
    assert any("not sorted" in p for p in probs) and any("outside the video" in p for p in probs)
    json.dumps(probs)


def test_both_hands_on_one_surface_is_one_finding():
    rows = [row(t / 10, "Person 1", side + "_wrist", "side-table-1", "nonsterile")
            for side in ("l", "r") for t in range(20, 40)]
    f = analyze(rows, {"Person 1": "sterile"}, LABELS, "s1")
    assert [x["title"] for x in f] == ["Person 1's hands touch Side table"]
    assert (f[0]["timestampSec"], f[0]["endSec"]) == (2.0, 3.9)


def test_one_frame_per_second_recordings_group_correctly():
    # MM-OR is captured at 1 frame/s: consecutive frames are 1 s apart and still one contact.
    rows = [row(float(t), "Person 2", "r_wrist", "tray-1", "sterile") for t in (10, 11, 12)]
    rows += [row(float(t), "Person 2", "r_wrist", "tray-1", "sterile") for t in (30,)]
    rows += [row(float(t), "Person 1", "l_elbow", "drape-1", "sterile") for t in range(0, 60)]  # sets the clock
    f = analyze(rows, {"Person 1": "sterile", "Person 2": "nonsterile"}, LABELS, "s1", Params(repeat_window_sec=0))
    assert [(x["timestampSec"], x["endSec"]) for x in f] == [(10.0, 12.0), (30.0, 30.0)]


def test_unscrubbed_touching_patient_is_breach_but_robot_is_neutral():
    labels = {**LABELS, "robot-1": "Robot"}
    rows = [row(t / 10, "Person 3", "r_wrist", "patient-1", "patient") for t in range(10, 20)]
    rows += [row(t / 10, "Person 3", "l_wrist", "robot-1", "neutral") for t in range(30, 40)]
    rows += [row(t / 10, "Person 1", "r_wrist", "robot-1", "neutral") for t in range(30, 40)]
    f = analyze(rows, {"Person 1": "sterile", "Person 3": "nonsterile"}, labels, "s1")
    assert [x["title"] for x in f] == ["Unscrubbed Person 3 touches Patient"]


def test_cap_keeps_the_strongest_findings_across_the_whole_recording():
    # 250 weak early findings (scrubbed hand on a side table) and one strong late one (unscrubbed
    # hand on the sterile tray). Cutting by time would drop the late one; ranking keeps it.
    labels = {**LABELS, **{f"table-{i}": f"Table {i}" for i in range(250)}}
    rows = [row(i * 4 + d, "Person 1", "r_wrist", f"table-{i}", "nonsterile") for i in range(250) for d in (0, 1)]
    rows += [row(t, "Person 2", "l_wrist", "tray-1", "sterile") for t in (2000.0, 2001.0)]
    rows = [{**r, "inside_mask": r["person_label"] == "Person 2"} for r in rows]
    f = analyze(rows, {"Person 1": "sterile", "Person 2": "nonsterile"}, labels, "s1")
    assert len(f) == MAX_FINDINGS
    assert f[-1]["title"] == "Unscrubbed Person 2 touches Instrument tray"
    assert [x["timestampSec"] for x in f] == sorted(x["timestampSec"] for x in f)
    assert [x["eventId"] for x in f[:2]] == ["evt-1", "evt-2"]
    assert not any(k.startswith("_") for x in f for k in x)
    assert timestamp_problems(f, 2100) == []


def test_repeated_contacts_become_one_finding():
    rows = [row(float(t), "Person 1", "r_wrist", "side-table-1", "nonsterile") for t in (10, 11, 25, 26, 50, 51)]
    rows += [row(float(t), "Person 3", "l_elbow", "drape-1", "sterile") for t in range(0, 300)]  # sets the clock
    people = {"Person 1": "sterile", "Person 3": "sterile"}
    f = analyze(rows, people, LABELS, "s1")
    assert [(x["timestampSec"], x["endSec"]) for x in f] == [(10.0, 51.0)]
    assert "3 times" in f[0]["description"]
    assert [e["timestampSec"] for e in f[0]["evidence"]] == [10.0, 25.0, 50.0]
    assert timestamp_problems(f, 300) == []
    # A repeat after the window, or past the longest span, is a new finding.
    assert len(analyze(rows, people, LABELS, "s1", Params(repeat_window_sec=10))) == 3
    assert len(analyze(rows, people, LABELS, "s1", Params(max_repeat_span_sec=20))) == 2


def test_stricter_contact_checks_and_single_frame_rule():
    base = {"pixel_dist": 6.0, "depth_gap": 0.06, "speed_px_s": 300.0}
    rows = [{**row(float(t), "Person 2", "r_wrist", "tray-1", "sterile"), **base} for t in (10, 11)]
    rows += [row(float(t), "Person 1", "l_elbow", "drape-1", "sterile") for t in range(0, 60)]  # sets the clock
    people = {"Person 1": "sterile", "Person 2": "nonsterile"}
    assert len(analyze(rows, people, LABELS, "s1")) == 1
    for strict in (Params(contact_px=4), Params(max_depth_gap=0.05), Params(max_speed_px_s=200)):
        assert analyze(rows, people, LABELS, "s1", strict) == []
    assert len(analyze(rows, people, LABELS, "s1", Params(low_fps_min_frames=3))) == 0
    # At 1 frame/s a single-frame touch counts only inside the surface outline.
    one = [{**row(40.0, "Person 2", "r_wrist", "tray-1", "sterile"), "inside_mask": False}] + rows[2:]
    assert analyze(one, people, LABELS, "s1") == []
    assert len(analyze(one, people, LABELS, "s1", Params(single_frame_needs_inside=False))) == 1


def test_scrubbed_nonsterile_rule_can_be_turned_off():
    rows = [row(t / 10, "Person 1", "r_wrist", "side-table-1", "nonsterile") for t in range(20, 31)]
    assert len(analyze(rows, {"Person 1": "sterile"}, LABELS, "s1")) == 1
    assert analyze(rows, {"Person 1": "sterile"}, LABELS, "s1", Params(scrubbed_nonsterile_findings=False)) == []


def test_load_params_from_file(tmp_path, caplog):
    assert load_params(tmp_path / "missing.json") == Params()
    path = tmp_path / "breach_params.json"
    path.write_text(json.dumps({"params": {"repeat_window_sec": 10, "contact_px": 4.0, "old_setting": 1},
                                "tuned_on": "val"}))
    p = load_params(path)
    assert (p.repeat_window_sec, p.contact_px, p.chain_window_sec) == (10, 4.0, Params().chain_window_sec)
    assert "old_setting" in caplog.text


def test_rule_outranks_uncertainty_and_length_at_the_cap():
    # A long, low-uncertainty scrubbed contact must not push out a short, uncertain unscrubbed breach.
    rows = [{**row(t / 10, "Person 1", "r_wrist", "side-table-1", "nonsterile"), "depth_gap": 0.01}
            for t in range(0, 300)]
    rows += [{**row(t / 10, "Person 2", "l_wrist", "tray-1", "sterile"), "inside_mask": False}
             for t in (400, 401)]
    f = analyze(rows, {"Person 1": "sterile", "Person 2": "nonsterile"}, LABELS, "s1", Params(max_findings=1))
    assert [x["title"] for x in f] == ["Unscrubbed Person 2 touches Instrument tray"]
    assert f[0]["uncertainty"]["level"] == "high"


def test_frame_spacing_comes_from_the_video_not_sparse_contacts():
    # The worker loads only contact rows. Two lone 1-frame touches 3 s apart in a 30 fps video look like
    # one contact in a 1-frame-per-3-s recording unless the real frame spacing is passed in; at 30 fps
    # they are two single-frame flickers and are dropped.
    rows = [row(t, "Person 2", "r_wrist", "tray-1", "sterile") for t in (10.0, 13.0)]
    people = {"Person 2": "nonsterile"}
    assert [(x["timestampSec"], x["endSec"]) for x in analyze(rows, people, LABELS, "s1")] == [(10.0, 13.0)]
    assert analyze(rows, people, LABELS, "s1", frame_dt=1 / 30) == []


def test_role_at_the_moment_of_contact_wins_over_the_final_role():
    # Final vote says unscrubbed (e.g. the label later landed on someone else), but at the time of these
    # contacts the person was shown as scrubbed: touching the patient is then not a finding.
    rows = [{**row(t, "Person 2", "r_index_tip", "patient-1", "patient"), "person_designation": "sterile"}
            for t in (4.0, 5.0, 6.0)]
    assert analyze(rows, {"Person 2": "nonsterile"}, LABELS, "s", frame_dt=1.0) == []
    # Older rows without the per-frame role keep using the final role.
    old = [{k: v for k, v in r.items() if k != "person_designation"} for r in rows]
    assert [f["title"] for f in analyze(old, {"Person 2": "nonsterile"}, LABELS, "s", frame_dt=1.0)] == [
        "Unscrubbed Person 2 touches Patient"]
    events = group_events(rows, {"Person 2": "nonsterile"}, LABELS, Params(), 1.0)
    assert [e.person_designation for e in events] == ["sterile"]


def test_contacts_with_a_surface_whose_id_changes_are_one_finding():
    # The patient outline gets a new ID at each keyframe (patient-3, patient-4, ...).
    labels = {f"patient-{i}": "Patient" for i in range(3, 9)}
    rows = [{**row(t, "Person 2", "r_index_tip", f"patient-{i}", "patient"), "person_designation": "nonsterile"}
            for i, t in zip(range(3, 9), (4.0, 6.0, 10.0, 14.0, 20.0, 24.0))]
    findings = analyze(rows, {"Person 2": "nonsterile"}, labels, "s", frame_dt=2.0)
    assert len(findings) == 1
    f = findings[0]
    assert (f["timestampSec"], f["endSec"]) == (4.0, 24.0)
    assert "contacts the patient (" in f["description"] and "Patient Patient" not in f["description"]
