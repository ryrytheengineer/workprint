"""HUD overlays: the tracker, the counter, the rail."""
import cv2
import numpy as np

from workprint import cli, ff, hud, manifest
from workprint.render import plan, render
from tests.test_voice import three_slot_cut


def scene(k, size=(180, 320)):
    rng = np.random.default_rng(1)
    frame = cv2.GaussianBlur(rng.integers(0, 255, (*size, 3), dtype=np.uint8), (0, 0), 6)
    patch = cv2.GaussianBlur(np.random.default_rng(2).integers(0, 255, (40, 40, 3), dtype=np.uint8), (0, 0), 1.5)
    x, y = 40 + 3 * k, 60 + k
    frame[y:y + 40, x:x + 40] = patch
    return frame, (x, y)


def test_the_follower_stays_on_a_moving_subject():
    first, (x, y) = scene(0)
    follower = hud.Follower(first, (x, y, 40, 40))
    for k in range(1, 40):
        frame, (tx, ty) = scene(k)
        bx, by, _, _ = follower.step(frame)
    assert abs(bx - tx) < 5 and abs(by - ty) < 5 and follower.score > 0.6  # 117 px later, still on it


def test_counter_rail_and_track_are_drawn():
    h = hud.Hud([{"id": "h1", "kind": "counter", "at": 0.0, "dur": 2.0, "from": 0, "to": 3900, "suffix": " HRS", "pos": [0.1, 0.8]},
                 {"id": "h2", "kind": "rail", "at": 0.0, "dur": 2.0, "label": "unit", "timecode": True},
                 {"id": "h3", "kind": "track", "at": 0.5, "dur": 1.0, "box": [0.125, 0.33, 0.125, 0.22], "label": "target", "readout": True}], 24.0, 320, 180)
    blank = np.zeros((180, 320, 3), np.uint8)
    a, b = h.draw(blank.copy(), 0), h.draw(blank.copy(), 47)
    assert a[int(0.8 * 180):int(0.8 * 180) + 14, 30:140].max() > 120 and not np.array_equal(a, b)  # the number is there and it runs
    m = int(round(0.055 * 180))
    assert a[m, 160].max() > 100 and a[180 - m, 160].max() > 100 and a[90, 160].max() == 0  # rules top and bottom, nothing mid-frame
    assert h.draw(blank.copy(), 100).max() == 0 and not h.active(100)
    moving = hud.Hud([{"id": "h3", "kind": "track", "at": 0.0, "dur": 2.0, "box": [40 / 320, 60 / 180, 40 / 320, 40 / 180]}], 24.0, 320, 180)
    for k in range(30):
        frame, (x, y) = scene(k)
        out = moving.draw(frame.copy(), k)
    green = (out[..., 1] > 200) & (out[..., 0] < 215) & (out[..., 2] < 180)
    ys, xs = np.nonzero(green)
    assert len(xs) > 20 and abs(xs.min() - x) < 6 and abs(ys.min() - y) < 6  # the brackets are where the subject went
    errors, warnings = hud.problems({"format": {"fps": 24}, "cuts": [{"at": 0}, {"at": 1.0}], "hud": [
        {"id": "a", "kind": "track", "at": 0.5, "dur": 1.0, "box": [0.1, 0.1, 0.2, 0.2]}, {"id": "b", "kind": "track", "at": 0, "dur": 1, "box": [2, 0, 1, 1]},
        {"id": "c", "kind": "gauge", "at": 0, "dur": 1}, {"id": "d", "kind": "counter", "at": 0, "dur": 1}]})
    assert len(errors) == 3 and any("across a cut" in w for w in warnings)


def test_hud_elements_render_through_the_cache(project):
    project.save_cut(three_slot_cut(project), "three slots")
    before = plan(project, project.cut(), 0.5, 30, "ultrafast")["paths"]
    root = str(project.root)
    assert cli.main(["-p", root, "new", "hud", "kind=counter", "at=2.2", "dur=1.5", "from=0", "to=100", "suffix=%", "pos=[0.1,0.5]"]) == 0
    assert cli.main(["-p", root, "new", "hud", "kind=track", "at=4.2", "dur=1.2", "box=[0.3,0.3,0.2,0.3]", "label=unit 7"]) == 0
    cut = project.cut()
    assert [h["id"] for h in cut["hud"]] == ["h001", "h002"]
    after = plan(project, cut, 0.5, 30, "ultrafast")["paths"]
    assert [p == q for p, q in zip(before, after)] == [True, False, False]  # the first shot has no instruments and is untouched
    out = project.root / "hud.mp4"
    render(project, three_slot_cut(project), project.root / "plain.mp4", 0.5, 16, "ultrafast", progress=lambda *_: None)
    render(project, cut, out, 0.5, 16, "ultrafast", progress=lambda *_: None)
    for t in (3.0, 4.8):
        assert np.abs(ff.grab_frame(out, t).astype(int) - ff.grab_frame(project.root / "plain.mp4", t).astype(int)).max() > 60
    assert np.array_equal(ff.grab_frame(out, 1.0), ff.grab_frame(project.root / "plain.mp4", 1.0))
    assert cli.main(["-p", root, "remove", "h001"]) == 0 and len(project.cut()["hud"]) == 1
    assert manifest.validate({**cut, "hud": [{"id": "h9", "kind": "dial", "at": 0, "dur": 1}]}, project)[0]
