import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from mmor_fixture import make_fake_mmor, make_scene

from training.build_pose_dataset import match_people
from training.mmor import ClassMap, class_polygons, iter_annotated_frames, person_regions

BACKEND = Path(__file__).resolve().parent.parent


def run(module: str, *args: str) -> str:
    out = subprocess.run([sys.executable, "-m", module, *args], cwd=BACKEND, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.fixture(scope="module")
def mmor(tmp_path_factory) -> Path:
    return make_fake_mmor(tmp_path_factory.mktemp("MM-OR_data"))


def test_class_map_merges_roles_and_instruments():
    cm = ClassMap.load()
    assert cm.label_to_class[10] == cm.label_to_class[12] == "scrubbed_person"
    assert cm.label_to_class[8] == cm.label_to_class[7] == "unscrubbed_person"
    assert cm.label_to_class[13] == cm.label_to_class[16] == "instrument"
    assert cm.class_designation["sterile_drape"] == "sterile"
    assert cm.class_designation["operating_table"] == "nonsterile"
    assert cm.class_designation["patient"] == "patient"
    assert cm.class_id(14) is None  # annotation mistake label


def test_inference_config_covers_every_trained_class():
    cm = ClassMap.load()
    cfg = yaml.safe_load((BACKEND / "config" / "surfaces_mmor.yaml").read_text())
    prompts = {e["prompt"]: e["designation"] for e in cfg["surfaces"] + cfg["people"]}
    assert set(prompts) == set(cm.class_names)
    assert prompts == cm.class_designation


def test_iter_frames_uses_splits_and_skips_interpolated(mmor):
    frames = list(iter_annotated_frames(mmor, {"train", "val", "test"}))
    by_split = {}
    for split, f in frames:
        by_split.setdefault(split, set()).add(f.take)
        assert not f.mask.stem.endswith("_interpolated") and f.image.exists()
    assert by_split == {"train": {"001_PKA", "003_TKA"}, "val": {"002_PKA"}, "test": {"004_PKA"}}
    assert {f.camera for _, f in frames} == {"azure1", "simstation0"}
    assert len(frames) == 4 * 6 * 2


def test_polygons_and_people_from_mask():
    cm = ClassMap.load()
    _img, mask = make_scene(0)
    polys = class_polygons(mask, cm, min_area_frac=0.0)
    names = {cm.class_names[c] for c, _ in polys}
    assert {"sterile_drape", "instrument_table", "operating_table", "patient", "scrubbed_person",
            "unscrubbed_person"} <= names
    for _, p in polys:
        assert p.min() >= 0 and p.max() <= 1
    people = person_regions(mask, cm)
    assert sorted(c for _, c, _, _ in people) == ["scrubbed_person", "unscrubbed_person"]


def test_build_seg_dataset(mmor, tmp_path):
    out = tmp_path / "seg"
    run("training.build_seg_dataset", "--mmor", str(mmor), "--out", str(out), "--every", "1", "--workers", "2")
    data = yaml.safe_load((out / "dataset.yaml").read_text())
    assert list(data["names"].values()) == ClassMap.load().class_names
    labels = sorted((out / "labels" / "train").glob("*.txt"))
    assert len(labels) == 2 * 6 * 2
    assert len(list((out / "images" / "val").glob("*.jpg"))) == 12
    line = labels[0].read_text().splitlines()[0].split()
    assert int(line[0]) in range(len(data["names"])) and len(line) >= 7
    stats = json.loads((out / "stats.json").read_text())
    assert stats["instances"]["train/scrubbed_person"] == 24


def test_build_reid_dataset(mmor, tmp_path):
    out = tmp_path / "reid"
    run("training.build_reid_dataset", "--mmor", str(mmor), "--out", str(out), "--every", "1", "--min-crops", "4")
    train_ids = {p.name for p in (out / "train").iterdir()}
    assert train_ids == {p.name for p in (out / "val").iterdir()}
    assert "mmor_001_PKA_scrubbed_person_10" in train_ids and len(train_ids) == 6
    assert not any("004_PKA" in i for i in train_ids)  # test take never used


def test_export_contacts(mmor, tmp_path):
    out = tmp_path / "contacts.jsonl"
    run("training.export_contacts", "--mmor", str(mmor), "--out", str(out))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 4 * 6 * 3  # 4 takes x 6 labeled frames x 3 relations
    breach = [r for r in rows if r["breach_candidate"]]
    assert {(r["subject"], r["object"]) for r in breach} == {("circulator", "instrument_table")}
    close = next(r for r in rows if r["predicate"] == "closeTo")
    assert close["object"] == "operating_table" and not close["contact"]
    assert rows[0]["azure_image_id"] == "000001"


def test_match_people_requires_every_gt_person():
    gt = [(0, 0, 10, 10), (20, 0, 30, 10)]
    dets = np.array([[21, 0, 30, 10], [0, 1, 10, 10], [50, 50, 60, 60]], float)
    assert match_people(gt, dets, 0.5) == {0: 1, 1: 0}
    assert match_people(gt, dets[:1], 0.5) is None


def test_eval_video_clock_and_scoring(mmor, tmp_path):
    vids, res = tmp_path / "videos", tmp_path / "results"
    run("training.make_eval_videos", "--mmor", str(mmor), "--out", str(vids), "--split", "test")
    meta = json.loads((vids / "004_PKA_simstation0.frames.json").read_text())
    # 12 one-second frames; labeled frame i was captured at second 2*i
    assert meta["fps"] == 1.0 and meta["frames"] == 12 and meta["duration_sec"] == 12.0
    assert meta["label_to_sec"] == {str(i): 2.0 * i for i in range(6)}
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", str(vids / "004_PKA_simstation0.mp4")],
                           capture_output=True, text=True)
    assert int(probe.stdout.strip()) == 12
    res.mkdir()
    # breach labeled at labeled frames 2-3 -> seconds 4-6; one finding on it and one far away
    (res / "004_PKA_simstation0.findings.json").write_text(json.dumps([
        {"eventId": "evt-1", "timestampSec": 4.2, "endSec": 6.0, "evidence": [{"timestampSec": 4.2}]},
        {"eventId": "evt-2", "timestampSec": 11.5, "endSec": 11.9, "evidence": []}]))
    out = run("training.evaluate_breaches", "--mmor", str(mmor), "--videos", str(vids), "--results", str(res),
              "--tolerance", "1")
    report = json.loads((res / "evaluation.json").read_text())
    s = report["summary"]
    assert s["breaches"] == 1 and s["found_breaches"] == 1 and s["recall"] == 1.0
    assert s["precision"] == 0.5 and s["timestamp_problems"] == 0
    assert s["mean_onset_error_sec"] == pytest.approx(0.2), out
    assert report["videos"][0]["labeled"][0]["breaches"] == ["circulator touching instrument_table"]


def test_final_check_skips_an_empty_test_split(tmp_path):
    import yaml

    from training.train import _has_images

    (tmp_path / "images/val").mkdir(parents=True)
    (tmp_path / "images/test").mkdir(parents=True)
    (tmp_path / "images/val/a.jpg").write_bytes(b"x")
    data = tmp_path / "dataset.yaml"
    data.write_text(yaml.safe_dump({"path": str(tmp_path), "val": "images/val", "test": "images/test"}))
    assert _has_images(data, "val") and not _has_images(data, "test")  # test split not downloaded
    (tmp_path / "images/test/b.jpg").write_bytes(b"x")
    assert _has_images(data, "test")
