"""The white box: a shot shown as a box on a plain field, slamming in like The Arsenal's."""
import numpy as np

from workprint.render import BOX_SLAM, box_slams, boxed


def _rect(frame):
    ys, xs = np.nonzero((frame != frame[5, 5]).any(2))
    return xs.max() - xs.min() + 1, ys.max() - ys.min() + 1, (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2


def test_box_lands_from_larger_and_settles():
    frame = np.full((1080, 1920, 3), 40, np.uint8)
    widths = [_rect(boxed(frame, {}, i, 14))[0] for i in range(5)]
    assert widths[0] > widths[1] > widths[2] > widths[3] == widths[4] == 1092
    assert abs(widths[0] - 1092 * BOX_SLAM[0]) <= 2


def test_box_settled_size_position_and_field():
    frame = np.full((1080, 1920, 3), 40, np.uint8)
    out = boxed(frame, {}, 6, 14)
    w, h, cx, cy = _rect(out)
    assert (w, h) == (1092, 838) and abs(cx - 960) <= 1 and abs(cy - 532) <= 1
    assert tuple(int(v) for v in out[5, 5][::-1]) == (244, 244, 241)  # BGR frame, #F4F4F1 field


def test_box_grows_out_when_asked():
    frame = np.full((1080, 1920, 3), 40, np.uint8)
    assert _rect(boxed(frame, {"out": True}, 13, 14))[0] > 1092
    assert _rect(boxed(frame, {}, 13, 14))[0] == 1092


def test_a_run_of_boxes_slams_once():
    slots = [{"cut": {}}, {"cut": {"box": True}}, {"cut": {"box": True}}]
    assert box_slams(slots, 1) is True and box_slams(slots, 2) is False
