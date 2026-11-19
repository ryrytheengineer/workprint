"""X-ray variants, flicker intercuts, eased ramps and smooth slow motion."""
import cv2
import numpy as np
import pytest

from workprint import check, cli, ff, manifest
from workprint.look import apply_fx, xray
from workprint.render import plan, render


def picture(seed=0, size=(180, 320)):
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (*size, 3), dtype=np.uint8), (0, 0), 5)
    cv2.circle(img, (100, 90), 40, (200, 180, 60), -1)
    return img


def test_the_plain_xray_is_unchanged_and_the_options_work():
    frame = picture()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    inv = cv2.add(255 - gray, cv2.convertScaleAbs(cv2.Laplacian(gray, cv2.CV_16S, ksize=3), alpha=1.5))
    old = cv2.merge([inv, cv2.convertScaleAbs(inv, alpha=0.92), cv2.convertScaleAbs(inv, alpha=0.78)])
    assert np.array_equal(apply_fx(frame, ["xray"], 0, 10), old)  # exactly what 0.1 drew
    green = xray(frame, {"tint": "#40ff80"})
    assert green[..., 1].mean() > green[..., 2].mean() > 0 and green[..., 1].mean() > green[..., 0].mean()
    assert not np.array_equal(xray(frame, {"deep": True}), old)


def test_xray_scan_pulse_and_flicker():
    frame, n = picture(), 12
    seen = xray(frame)
    start = apply_fx(frame, [{"name": "xray-scan"}], 0, n)
    half = apply_fx(frame, [{"name": "xray-scan"}], 6, n)
    done = apply_fx(frame, [{"name": "xray-scan"}], n - 1, n)
    assert np.array_equal(start[:, 20:], frame[:, 20:])  # nothing scanned yet
    edge = int(round(6 / 11 * 320))
    assert np.array_equal(half[:, :edge - 6], seen[:, :edge - 6]) and np.array_equal(half[:, edge + 6:], frame[:, edge + 6:])
    assert half[:, edge - 1:edge + 1].min() == 255  # the scan line
    assert np.array_equal(done[:, :300], seen[:, :300])
    band = apply_fx(frame, [{"name": "xray-scan", "width": 0.2, "dir": "down"}], 6, n)
    assert np.array_equal(band[:20], frame[:20]) and not np.array_equal(band, frame)  # a band, moving down, leaves the top as it was
    first = apply_fx(frame, [{"name": "xray-pulse"}], 0, n).astype(int)
    last = apply_fx(frame, [{"name": "xray-pulse"}], n - 1, n).astype(int)
    assert np.abs(first - seen).mean() < 1 and np.abs(last - frame).mean() < 1
    states = [np.array_equal(apply_fx(frame, [{"name": "xray-flicker", "every": 2}], k, n), frame) for k in range(8)]
    assert states == [False, False, True, True, False, False, True, True]
    assert manifest.alternate_frames(10, 2, 9, pattern=[1, 3]) == {3, 4, 5, 7, 8}


def slots(project, **extra) -> dict:
    cut = manifest.new_cut(project.format, 3.5, "effects")
    cut["cuts"] = [{"at": 0.0, "src": "A003", "in": 0.5, **extra}, {"at": 2.0, "src": "A001", "in": 0.2}]
    return manifest.normalize(cut)


def frames_of(path, count, fps=24.0):
    reader = ff.FrameReader(path, 0.0, fps, (ff.probe(path)["width"], ff.probe(path)["height"]))
    out = [reader.read() for _ in range(count)]
    reader.close()
    return out


def test_a_slot_can_flicker_to_another_shot(project):
    quiet = lambda *_: None
    main, other = project.root / "a.mp4", project.root / "b.mp4"
    render(project, slots(project), main, 0.5, 18, "ultrafast", progress=quiet)
    twin = slots(project)
    twin["cuts"][0].update({"src": "A004", "in": 1.0})
    render(project, twin, other, 0.5, 18, "ultrafast", progress=quiet)
    cut = slots(project, intercut={"src": "A004", "in": 1.0, "every": 3, "from": 0.5})
    assert manifest.validate(cut, project)[0] == []
    out = project.root / "c.mp4"
    render(project, cut, out, 0.5, 18, "ultrafast", progress=quiet)
    a, b, c = frames_of(main, 40), frames_of(other, 40), frames_of(out, 40)
    on = manifest.intercut_frames(cut["cuts"][0], 48, 24.0)
    assert min(on) == 15 and {15, 16, 17, 21, 22, 23} <= on and 18 not in on and 5 not in on
    for k in (5, 13, 15, 17, 18, 20, 22, 30, 35):
        want, wrong = (b, a) if k in on else (a, b)
        near = np.abs(c[k].astype(int) - want[k].astype(int)).mean()
        far = np.abs(c[k].astype(int) - wrong[k].astype(int)).mean()
        assert near < 3 and far > 3 * near + 2, f"frame {k}: {near:.1f} from the expected shot, {far:.1f} from the other"
    report = check.check(project, cut, out, write_review=False)
    assert report["cuts"]["unplanned"] == 0 and report["verdict"] != "FAIL", [f["text"] for f in report["findings"]]
    bad = slots(project, intercut={"src": "A999", "in": 0})
    assert any("intercut" in e for e in manifest.validate(bad, project)[0])
    project.save_cut(slots(project), "plain")
    shot = project.shots()[0]["id"]
    assert cli.main(["-p", str(project.root), "intercut", "c001", "--shot", shot, "--every", "2"]) == 0
    assert project.cut()["cuts"][0]["intercut"]["every"] == 2
    assert cli.main(["-p", str(project.root), "intercut", "c001", "--off"]) == 0 and "intercut" not in project.cut()["cuts"][0]


def changes(path, count):
    f = frames_of(path, count)
    return np.array([np.abs(f[k + 1].astype(int) - f[k].astype(int)).mean() for k in range(len(f) - 1)])


def test_slow_motion_can_be_smooth_and_ramps_can_ease(project):
    quiet = lambda *_: None
    stepped, blended, flowed = project.root / "s.mp4", project.root / "bl.mp4", project.root / "fl.mp4"
    base = slots(project, speed=0.5)
    render(project, base, stepped, 0.5, 16, "ultrafast", progress=quiet)
    smooth = slots(project, speed=0.5, interp="blend")
    assert plan(project, smooth, 0.5, 16, "ultrafast")["todo"] == [0]  # only that slot changes
    render(project, smooth, blended, 0.5, 16, "ultrafast", progress=quiet)
    render(project, slots(project, speed=0.5, interp="flow"), flowed, 0.5, 16, "ultrafast", progress=quiet)
    d_step, d_blend, d_flow = changes(stepped, 44)[2:], changes(blended, 44)[2:], changes(flowed, 44)[2:]
    moving = np.median(d_step[d_step > 0.3]) if (d_step > 0.3).any() else 0
    assert moving > 0, "the test clip does not move"
    held = lambda d: np.mean(d < 0.25 * moving)
    assert held(d_step) > 0.3  # half speed by repeating: every other step shows nothing new
    assert held(d_blend) < 0.1 and held(d_flow) < 0.1  # every frame moves
    assert d_blend.std() < d_step.std() and ff.probe(flowed)["width"] == ff.probe(stepped)["width"]
    eased = slots(project, speed=[2.0, 0.5], ramp="inout", interp="blend")
    assert manifest.validate(eased, project)[0] == []
    stats = render(project, eased, project.root / "e.mp4", 0.5, 16, "ultrafast", progress=quiet)
    assert stats["underrun_frames"] == 0 and stats["frames"] == 84
    assert manifest.source_span({"in": 1.0, "speed": [2.0, 0.5], "ramp": "in"}, 48, 24.0)[1] == pytest.approx(1.0 + 2.0 * (2.0 - 1.5 / 3))
    assert any("ramp" in e for e in manifest.validate(slots(project, ramp="bounce"), project)[0])
    assert any("interp" in e for e in manifest.validate(slots(project, interp="magic"), project)[0])
