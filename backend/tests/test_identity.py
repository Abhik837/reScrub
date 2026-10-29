import numpy as np

from rescrub.pipeline.identity import IdentityResolver
from rescrub.pipeline.people import PersonObs


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


def obs(track_id, x, emb=None):
    return PersonObs(track_id, (x, 100, x + 100, 400), 0.9, {}, None if emb is None else unit(emb))


def test_new_tracks_get_sequential_labels():
    r = IdentityResolver(frame_diag=1000)
    a, b = obs(1, 0, [1, 0]), obs(2, 500, [0, 1])
    r.assign([a, b], 0.0)
    assert (a.person_label, b.person_label) == ("Person 1", "Person 2")


def test_lost_track_is_merged_back_by_appearance():
    r = IdentityResolver(frame_diag=1000)
    r.assign([obs(1, 0, [1, 0]), obs(2, 500, [0, 1])], 0.0)
    r.assign([obs(2, 500, [0, 1])], 1.0)  # track 1 occluded
    back = obs(7, 60, [0.98, 0.05])  # tracker gave it a new ID
    r.assign([back, obs(2, 500, [0, 1])], 3.0)
    assert back.person_label == "Person 1"
    assert len(r.people) == 2


def test_visible_person_is_never_assigned_twice():
    r = IdentityResolver(frame_diag=1000)
    r.assign([obs(1, 0, [1, 0])], 0.0)
    twin = obs(2, 20, [1, 0])  # same gown, standing next to Person 1
    first = obs(1, 0, [1, 0])
    r.assign([twin, first], 0.1)
    assert first.person_label == "Person 1"
    assert twin.person_label == "Person 2"


def test_dissimilar_or_far_track_becomes_new_person():
    r = IdentityResolver(frame_diag=1000, max_speed_frac=0.1)
    r.assign([obs(1, 0, [1, 0])], 0.0)
    r.assign([], 0.5)
    far = obs(2, 900, [1, 0])  # same look but impossibly far after 0.5 s
    r.assign([far], 0.5)
    assert far.person_label == "Person 2"


def test_roles_vote_scrubbed_or_unscrubbed():
    from rescrub.pipeline.surfaces import PersonRole

    r = IdentityResolver(frame_diag=1000)
    a, b = obs(1, 0, [1, 0]), obs(2, 300, [0, 1])  # boxes x 0..100 and 300..400, y 100..400
    big = obs(3, 250, [1, 1])
    big.box = (250, 0, 500, 500)  # a neighbour whose large box also contains Person 2
    r.assign([a, b, big], 0.0)
    assert r.designation("Person 1") == "sterile"  # default: assumed scrubbed

    mask = np.zeros((500, 500), bool)
    mask[120:390, 310:390] = True  # Person 2's body
    r.apply_roles([a, b, big], [PersonRole("Unscrubbed", "nonsterile", 0.9, mask)])
    assert r.designation("Person 2") == "nonsterile"
    assert r.designation("Person 1") == r.designation("Person 3") == "sterile"


def test_one_label_per_person_per_frame_when_old_track_returns():
    r = IdentityResolver(frame_diag=1000)
    r.assign([obs(1, 0, [1, 0]), obs(2, 500, [0, 1])], 0.0)
    r.assign([obs(2, 500, [0, 1])], 1.0)                 # track 1 lost
    r.assign([obs(9, 20, [1, 0]), obs(2, 500, [0, 1])], 2.0)  # re-identified as Person 1 under track 9
    back, new, b = obs(1, 0, [1, 0]), obs(9, 20, [1, 0]), obs(2, 500, [0, 1])
    r.assign([back, new, b], 3.0)                       # old track 1 returns while 9 is still alive
    labels = [back.person_label, new.person_label, b.person_label]
    assert len(set(labels)) == 3 and new.person_label == "Person 1"
