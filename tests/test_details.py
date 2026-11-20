"""The fast details flash: single details of the picture lit for a frame, found by a quick luma-key roto."""
import numpy as np

from workprint import manifest
from workprint.look import apply_fx, detail_mask, flash_detail


def scene():
    """A light sky over a dark ground, a dark bar (a wing) in the sky, and two light marks (lettering) on the ground."""
    f = np.full((90, 160, 3), 200, np.uint8)
    f[60:] = 40
    f[20:30, 40:120] = 25            # the wing
    f[70:76, 30:36] = 220            # a letter
    f[70:76, 50:56] = 220            # another
    return f


def test_dark_key_with_a_seed_takes_the_piece_under_it():
    m = detail_mask(scene(), {"box": [0.2, 0.15, 0.6, 0.3], "key": "dark", "seed": [0.5, 0.27]})
    assert m[25, 80] > 0.9 and m[25, 41] > 0.9          # the wing
    assert m[15, 80] < 0.1 and m[50, 80] < 0.1          # not the sky around it
    assert m[75, 33] == 0                               # nothing outside the box


def test_a_seed_between_pixels_snaps_to_the_nearest_piece():
    m = detail_mask(scene(), {"box": [0.2, 0.15, 0.6, 0.3], "key": "dark", "seed": [0.5, 0.17]})
    assert m[25, 80] > 0.9


def test_inside_drops_what_touches_the_box_edge():
    spot = {"box": [0.1, 0.6, 0.4, 0.35], "key": "light"}
    assert detail_mask(scene(), spot)[56, 20] > 0.9                         # the sky strip at the top edge is kept
    m = detail_mask(scene(), {**spot, "inside": True})
    assert m[73, 33] > 0.9 and m[73, 53] > 0.9 and m[56, 20] < 0.1          # only the letters


def test_a_set_level_splits_three_tones():
    f = scene()
    f[60:, 100:] = 90                                   # a mid-grey patch beside the wing's shadow
    f[64:80, 120:124] = 10                              # a thin black strut on it
    m = detail_mask(f, {"box": [0.6, 0.68, 0.35, 0.3], "key": "dark", "level": 0.12})
    assert m[70, 121] > 0.9 and m[70, 110] < 0.1


def test_fill_invert_and_outline():
    f = scene()
    filled = flash_detail(f, {"box": [0.2, 0.15, 0.6, 0.3], "key": "dark", "seed": [0.5, 0.27], "mode": "fill"})
    assert tuple(filled[25, 80]) == (241, 244, 244)     # #f4f4f1, in BGR
    assert tuple(filled[15, 80]) == tuple(f[15, 80])
    neg = flash_detail(f, {"box": [0.25, 0.5, 0.5, 0.25], "mode": "invert"})
    y0, y1, x0, x1 = 45, 68, 40, 120
    assert (neg[y0:y1, x0:x1] == 255 - f[y0:y1, x0:x1]).all()
    assert (neg[:40] == f[:40]).all() and (neg[:, :38] == f[:, :38]).all()
    traced = flash_detail(f, {"box": [0.2, 0.15, 0.6, 0.3], "key": "dark", "seed": [0.5, 0.27], "mode": "outline"})
    changed = (traced != f).any(axis=2)
    assert changed[20, 80] or changed[19, 80]            # the wing's edge is traced
    assert not changed[25, 80]                           # its middle is not filled


def test_outline_does_not_trace_the_box_edge():
    f = scene()
    traced = flash_detail(f, {"box": [0.4, 0.15, 0.6, 0.3], "key": "dark", "mode": "outline"})  # cuts the wing at x=64
    changed = (traced != f).any(axis=2)
    assert not changed[22:28, 63:66].any()


def test_spots_light_only_their_own_frames():
    f = scene()
    fx = [{"name": "details", "spots": [{"frame": 3, "box": [0.2, 0.15, 0.6, 0.3], "key": "dark", "seed": [0.5, 0.27]}]}]
    assert (apply_fx(f, fx, 2, 10) == f).all()
    assert not (apply_fx(f, fx, 3, 10) == f).all()
    assert (apply_fx(f, fx, 4, 10) == f).all()


def test_validation_catches_bad_spots():
    good = {"name": "details", "spots": [{"frame": 2, "box": [0.1, 0.1, 0.3, 0.3], "seed": [0.2, 0.2]}]}
    assert manifest.detail_problems(good, 10) == []
    assert manifest.detail_problems({"name": "details"}, 10)
    assert any("outside the slot" in e for e in manifest.detail_problems({"name": "details", "spots": [{"frame": 12, "box": [0.1, 0.1, 0.3, 0.3]}]}, 10))
    assert any("unknown mode" in e for e in manifest.detail_problems({"name": "details", "spots": [{"box": [0.1, 0.1, 0.3, 0.3], "mode": "glow"}]}, 10))
    assert any("seed" in e for e in manifest.detail_problems({"name": "details", "spots": [{"box": [0.1, 0.1, 0.3, 0.3], "seed": [0.9, 0.9]}]}, 10))
    assert any("box" in e for e in manifest.detail_problems({"name": "details", "spots": [{"box": [0.1, 0.1, 0.0, 0.3]}]}, 10))
