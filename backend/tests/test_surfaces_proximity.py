import numpy as np
import pytest

from rescrub.pipeline.people import PersonObs
from rescrub.pipeline.proximity import ProximityAnalyzer
from rescrub.pipeline.surfaces import parse_zones

ZONES = [
    {"label": "Side table", "designation": "nonsterile", "polygon": [[0, 0.5], [1, 0.5], [1, 1], [0, 1]]},
    {"label": "Drape", "designation": "sterile", "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]]},
]


def test_zones_normalized_and_pixel_coords():
    s = parse_zones(ZONES, 200, 200)
    assert [z.surface_id for z in s] == ["side-table-1", "drape-1"]
    assert s[0].mask[150, 10] and not s[0].mask[50, 10]
    # earlier zone wins the overlap (rows 100..)
    assert not s[1].mask[100, 50] and s[1].mask[50, 50]


@pytest.mark.parametrize("bad", [
    [{"label": "x", "designation": "clean", "polygon": [[0, 0], [1, 0], [1, 1]]}],
    [{"label": "x", "designation": "sterile", "polygon": [[0, 0], [1, 0]]}],
    {"not": "a list"},
])
def test_bad_zones_rejected(bad):
    with pytest.raises(ValueError):
        parse_zones(bad, 100, 100)


def person(points):
    p = PersonObs(1, (0, 0, 10, 10), 0.9, points)
    p.person_label = "Person 1"
    return p


def test_inside_surface_is_candidate_contact():
    s = parse_zones(ZONES[:1], 200, 200)
    pa = ProximityAnalyzer(near_px=40, contact_px=8, contact_depth_gap=0.1, max_speed_px_s=400)
    rows, _ = pa.analyze([person({"r_wrist": (50, 150, 0.9), "r_shoulder": (50, 150, 0.9)})], s, 0.0, None)
    assert len(rows) == 1  # shoulders are not contact points
    r = rows[0]
    assert r.inside_mask and r.pixel_dist == 0 and r.candidate_contact and r.designation == "nonsterile"


def test_far_points_produce_no_rows_and_near_points_are_not_contacts():
    s = parse_zones(ZONES[:1], 200, 200)
    pa = ProximityAnalyzer(near_px=40, contact_px=8, contact_depth_gap=0.1, max_speed_px_s=400)
    rows, _ = pa.analyze([person({"r_wrist": (50, 20, 0.9)})], s, 0.0, None)
    assert rows == []
    rows, _ = pa.analyze([person({"r_wrist": (50, 80, 0.9)})], s, 0.1, None)
    assert len(rows) == 1 and not rows[0].candidate_contact and 19 <= rows[0].pixel_dist <= 21


def test_depth_gap_separates_hovering_from_touching():
    s = parse_zones(ZONES[:1], 200, 200)
    depth = np.zeros((200, 200), np.float32)
    depth[150, 50] = 0.5  # the hand is much closer to the camera than the table
    pa = ProximityAnalyzer(near_px=40, contact_px=8, contact_depth_gap=0.1, max_speed_px_s=400)
    rows, point_depth = pa.analyze([person({"r_wrist": (50, 150, 0.9)})], s, 0.0, depth)
    assert point_depth[("Person 1", "r_wrist")] == 0.5
    assert rows[0].depth_gap == pytest.approx(0.5) and not rows[0].candidate_contact


def test_fast_motion_is_not_a_contact():
    s = parse_zones(ZONES[:1], 200, 200)
    pa = ProximityAnalyzer(near_px=40, contact_px=8, contact_depth_gap=0.1, max_speed_px_s=400)
    pa.analyze([person({"r_wrist": (10, 150, 0.9)})], s, 0.0, None)
    rows, _ = pa.analyze([person({"r_wrist": (150, 150, 0.9)})], s, 0.1, None)  # 1400 px/s
    assert rows[0].speed_px_s == pytest.approx(1400) and not rows[0].candidate_contact


def test_surface_config_uses_the_trained_model_when_it_is_there(tmp_path):
    from rescrub.settings import Settings

    s = Settings(_env_file=None, models_dir=tmp_path, surface_config="")
    assert s.resolved_surface_config().name == "surfaces.yaml"
    (tmp_path / "trained").mkdir()
    (tmp_path / "trained" / "rescrub-or-seg.pt").write_bytes(b"weights")
    assert s.resolved_surface_config().name == "surfaces_mmor.yaml"
    chosen = Settings(_env_file=None, models_dir=tmp_path, surface_config="config/surfaces.yaml")
    assert chosen.resolved_surface_config().name == "surfaces.yaml"


def test_pose_and_identity_use_the_trained_models_when_they_are_there(tmp_path):
    from rescrub.settings import Settings

    s = Settings(_env_file=None, models_dir=tmp_path, pose_model="", embed_model="")
    assert (s.resolved_pose_model(), s.resolved_embed_model()) == ("yolo26m-pose.pt", "yolo26n-cls.pt")
    (tmp_path / "trained").mkdir()
    for name in ("rescrub-or-pose.pt", "rescrub-reid-cls.pt"):
        (tmp_path / "trained" / name).write_bytes(b"weights")
    assert s.resolved_pose_model() == "trained/rescrub-or-pose.pt"
    assert s.resolved_embed_model() == "trained/rescrub-reid-cls.pt"
    chosen = Settings(_env_file=None, models_dir=tmp_path, pose_model="yolo26n-pose.pt", embed_model="none")
    assert (chosen.resolved_pose_model(), chosen.resolved_embed_model()) == ("yolo26n-pose.pt", None)
