"""Hand points from RTMW are kept only when they belong to the person (rescrub/pipeline/hands.py)."""

from rescrub.pipeline.hands import own_hand_points

BOX = (100.0, 100.0, 300.0, 500.0)  # 200 x 400 px person


def test_points_near_the_pose_wrist_are_kept():
    found = {"r_hand_wrist": (250.0, 300.0, 0.9), "r_index_tip": (262.0, 330.0, 0.8)}
    assert own_hand_points(found, BOX, {"r_wrist": (245.0, 295.0, 0.9)}) == found


def test_points_outside_the_person_are_dropped():
    found = {"r_hand_wrist": (250.0, 300.0, 0.9), "r_index_tip": (520.0, 330.0, 0.8)}  # far right of the box
    assert own_hand_points(found, BOX, {"r_wrist": (245.0, 295.0, 0.9)}) == {"r_hand_wrist": (250.0, 300.0, 0.9)}


def test_a_hand_far_from_this_persons_wrist_is_dropped():
    # Inside the box, but the hand's wrist is 300 px from this person's wrist: a neighbour's hand.
    found = {"l_hand_wrist": (120.0, 480.0, 0.9), "l_thumb_tip": (125.0, 470.0, 0.7),
             "r_hand_wrist": (250.0, 300.0, 0.9)}
    pose = {"l_wrist": (290.0, 230.0, 0.9), "r_wrist": (245.0, 295.0, 0.9)}
    assert own_hand_points(found, BOX, pose) == {"r_hand_wrist": (250.0, 300.0, 0.9)}


def test_without_a_pose_wrist_only_the_box_check_applies():
    found = {"l_index_tip": (150.0, 200.0, 0.8)}
    assert own_hand_points(found, BOX, {}) == found
