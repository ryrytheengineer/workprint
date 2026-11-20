"""Matte transitions, moving type, loops, covers, upload files, colour matching and a travelling version frame."""
import cv2
import numpy as np
import pytest

from workprint import captions, check, cli, ff, finish, manifest, matte, versions
from workprint.look import apply_match, colour_stats
from workprint.render import plan, render
from tests.test_matte import left_half_subject  # noqa: F401
from tests.test_voice import three_slot_cut

QUIET = lambda *_: None


def test_the_matte_wipe_opens_from_the_subject(left_half_subject):
    old, new = np.full((90, 160, 3), 200, np.uint8), np.full((90, 160, 3), 20, np.uint8)
    alpha = np.zeros((90, 160), np.float32)
    alpha[20:70, 30:80] = 1.0
    early, mid, late = (matte.wipe(old, new, alpha, p) for p in (0.02, 0.35, 0.98))
    assert early[45, 55, 0] > 150 or early.mean() > 180  # still almost all the old shot
    assert mid[45, 55, 0] < 60 and mid[5, 150, 0] > 150  # the new shot is inside the subject, not yet at the far corner
    assert late.mean() < 40  # and then everywhere
    held = matte.wipe(old, new, alpha, 0.1, "hold")
    assert held[45, 55, 0] > 150 and held[5, 150, 0] < 40  # hold: new shot at once, subject lingers
    assert np.abs(matte.wipe(old, new, np.zeros((90, 160), np.float32), 0.5).astype(int) - 110).max() <= 1  # no subject: a dissolve


def test_a_matte_transition_renders_and_passes_the_check(project, left_half_subject):
    cut = three_slot_cut(project)
    cut["cuts"][1]["t"] = {"type": "matte", "frames": 12}
    assert manifest.validate(cut, project)[0] == []
    out = project.root / "m.mp4"
    stats = render(project, cut, out, 0.5, 20, "ultrafast", progress=QUIET)
    plain = project.root / "p.mp4"
    render(project, three_slot_cut(project), plain, 0.5, 20, "ultrafast", progress=QUIET)
    a, b = ff.grab_frame(out, 2.0 + 3 / 24), ff.grab_frame(plain, 2.0 + 3 / 24)
    assert stats["underrun_frames"] == 0 and np.abs(a.astype(int) - b.astype(int)).mean() > 2  # the old shot is still in the frame
    assert np.abs(ff.grab_frame(out, 3.5).astype(int) - ff.grab_frame(plain, 3.5).astype(int)).mean() < 2
    report = check.check(project, cut, out, write_review=False)
    assert report["verdict"] != "FAIL" and report["cuts"]["unplanned"] == 0


def test_captions_can_arrive_with_a_move():
    cue = {"at": 1.0, "dur": 1.0, "text": "WILL", "style": "punch", "set": {"in": "pop", "dim": 0.0}}
    pieces = captions.compile_cue(cue, 24.0, 640, 360)
    first, settled = np.zeros((360, 640, 3), np.uint8), np.zeros((360, 640, 3), np.uint8)
    captions.draw(pieces, first, 24)
    captions.draw(pieces, settled, 40)
    width = lambda f: np.ptp(np.nonzero(f[..., 0].max(0) > 60)[0])
    assert width(first) > width(settled) * 1.15 and first.max() < settled.max() + 1  # arrives larger, settles to size
    still = captions.compile_cue({**cue, "set": {"dim": 0.0}}, 24.0, 640, 360)
    plain = np.zeros((360, 640, 3), np.uint8)
    captions.draw(still, plain, 24)
    assert np.array_equal(plain, settled)  # without "in" nothing changes
    rise = captions.compile_cue({"at": 0, "dur": 1, "text": "one two", "style": "line", "set": {"in": "rise"}}, 24.0, 640, 360)
    f0, f9 = np.zeros((360, 640, 3), np.uint8), np.zeros((360, 640, 3), np.uint8)
    captions.draw(rise, f0, 0)
    captions.draw(rise, f9, 12)
    assert np.nonzero(f0[..., 0].max(1) > 40)[0].min() > np.nonzero(f9[..., 0].max(1) > 40)[0].min()  # starts lower
    errors, _ = captions.problems({"format": {"fps": 24}, "duration": 5, "captions": [{"id": "k", "at": 0, "dur": 1, "text": "x", "set": {"in": "spin"}}]})
    assert any("spin" in e for e in errors)


def test_loop_cover_and_upload_file(project):
    root = str(project.root)
    with_music = three_slot_cut(project)
    with_music["music"] = {"in": 12.5, "gain_db": 0}
    project.save_cut(with_music, "three slots and a track")
    assert cli.main(["-p", root, "render", "--proxy"]) == 0
    source = max((project.root / "renders").glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    looped = source.with_name(source.stem + "-loop.mp4")
    made = finish.loop(source, looped, 0.5)
    info = ff.probe(looped)
    assert made["frames"] == 144 - 12 and abs(info["duration"] - 5.5) < 0.1 and info["has_audio"]
    reader = ff.FrameReader(looped, 0.0, 24.0, (info["width"], info["height"]))
    frames = [reader.read() for _ in range(made["frames"])]
    reader.close()
    opening = ff.FrameReader(source, 0.0, 24.0, (info["width"], info["height"]))
    head = [opening.read() for _ in range(13)]
    opening.close()
    assert np.abs(frames[-1].astype(int) - head[11].astype(int)).mean() < 12  # the last frame has nearly become the opening
    assert np.abs(frames[0].astype(int) - head[12].astype(int)).mean() < 4  # and the loop starts where that hand-over ends
    assert cli.main(["-p", root, "cover", str(source), "--at", "3.0"]) == 0 and source.with_name(source.stem + "-cover.jpg").exists()
    assert 0.0 < finish.best_frame(source, 12) < 6.0
    assert cli.main(["-p", root, "deliver", str(source), "--mbps", "2"]) == 0
    upload = ff.probe(source.with_name(source.stem + "-upload.mp4"))
    assert abs(upload["duration"] - 6.0) < 0.1 and upload["has_audio"] and upload["width"] == info["width"]


def test_a_shot_can_be_matched_to_another(project):
    warm = np.full((60, 80, 3), (60, 120, 200), np.uint8) + np.random.default_rng(0).integers(0, 30, (60, 80, 3), dtype=np.uint8)
    cool = np.full((60, 80, 3), (190, 130, 80), np.uint8) + np.random.default_rng(1).integers(0, 12, (60, 80, 3), dtype=np.uint8)
    spec = {"from": colour_stats([cool]), "to": colour_stats([warm]), "amount": 1.0}
    moved = colour_stats([apply_match(cool, spec)])
    gap = lambda a, b: float(np.abs(np.array(a[0]) - np.array(b[0])).mean())
    assert gap(moved, colour_stats([warm])) < 0.15 * gap(colour_stats([cool]), colour_stats([warm]))
    half = colour_stats([apply_match(cool, {**spec, "amount": 0.5})])
    assert 0.35 < gap(half, colour_stats([warm])) / gap(colour_stats([cool]), colour_stats([warm])) < 0.65
    root = str(project.root)
    project.save_cut(three_slot_cut(project), "three slots")
    before = plan(project, project.cut(), 0.5, 30, "ultrafast")["paths"]
    assert cli.main(["-p", root, "match", "c002", "--to", "c001"]) == 0
    cut = project.cut()
    assert cut["cuts"][1]["match"]["ref"] == "c001"
    after = plan(project, cut, 0.5, 30, "ultrafast")["paths"]
    assert [p == q for p, q in zip(before, after)] == [True, False, True]
    render(project, cut, project.root / "matched.mp4", 0.5, 20, "ultrafast", progress=QUIET)
    assert cli.main(["-p", root, "match", "c002", "--off"]) == 0 and "match" not in project.cut()["cuts"][1]


def test_a_version_frame_can_travel_during_a_shot(project):
    cut = three_slot_cut(project)
    cut["cuts"][0].update({"focus_9x16": [0.0, 0.5], "focus_9x16_to": [1.0, 0.5]})
    fixed = three_slot_cut(project)
    fixed["cuts"][0]["focus_9x16"] = [0.0, 0.5]
    assert plan(project, cut, 0.5, 30, "ultrafast")["paths"] == plan(project, fixed, 0.5, 30, "ultrafast")["paths"]  # 16:9 unaffected
    moving, still = project.root / "t.mp4", project.root / "s.mp4"
    render(project, cut, moving, 0.5, 16, "ultrafast", progress=QUIET, aspect="9:16")
    render(project, fixed, still, 0.5, 16, "ultrafast", progress=QUIET, aspect="9:16")
    diff = lambda t: np.abs(ff.grab_frame(moving, t).astype(int) - ff.grab_frame(still, t).astype(int)).mean()
    assert diff(0.02) < 2.5 and diff(1.9) > 3 * diff(0.02) + 2  # starts on the same framing and ends somewhere else
    assert ff.probe(moving)["width"] == ff.probe(still)["width"] and diff(3.0) < 2.5  # the other shots are the same
    done = versions.propose(project, three_slot_cut(project), "9x16", 0.5625, follow=True)
    assert len(done) == 3


def test_letterbox_until_opens_the_frame_at_that_second():
    import numpy as np
    from workprint.look import Finish
    f = Finish({"letterbox": 2.39, "letterbox_until": 2.0}, 1920, 1080)
    frame = np.full((1080, 1920, 3), 200, np.uint8)
    assert f.apply(frame, 0)[0, 0, 0] == 200                 # the finish itself leaves the bars to the timeline
    before, after = f.bars(frame.copy(), 1.5), f.bars(frame.copy(), 2.0)
    assert before[0, 0, 0] == 0 and before[540, 960, 0] == 200 and before[-1, 0, 0] == 0
    assert f.bar == 138 and before[137, 0, 0] == 0 and before[138, 0, 0] == 200
    assert after[0, 0, 0] == 200


def test_a_cut_out_flies_in_straight_and_lands_in_place():
    back = np.full((90, 160, 3), 200, np.uint8)
    subject = np.full((90, 160, 3), 20, np.uint8)
    alpha = np.zeros((90, 160), np.float32)
    alpha[30:60, 40:80] = 1.0
    first = matte.revolve(subject, alpha, back, 0.0, 0.15, False, -1.0, steps=5, turn=0.0, rise=0.06, grow=0.12, shutter=0.45)
    last = matte.revolve(subject, alpha, back, 0.85, 1.0, False, -1.0, steps=5, turn=0.0, rise=0.06, grow=0.12, shutter=0.45)
    assert first[45, 60, 0] > 150                          # at the start it is still off to the left: its place shows the old shot
    assert last[45, 60, 0] < 60 and last[10, 150, 0] > 150  # at the end it sits in its place, the rest still the old shot


def test_a_fly_in_lands_then_its_background_flashes_in(project, left_half_subject):
    cut = three_slot_cut(project)
    cut["cuts"][1]["t"] = {"type": "matte", "frames": 8, "style": "fly-in", "spin": -1, "flash": 3}
    assert manifest.transition_of(cut["cuts"][1])["flash"] == 3
    assert manifest.validate(cut, project)[0] == []
    out, plain = project.root / "fly.mp4", project.root / "plain.mp4"
    stats = render(project, cut, out, 0.5, 20, "ultrafast", progress=QUIET)
    render(project, three_slot_cut(project), plain, 0.5, 20, "ultrafast", progress=QUIET)
    grab = lambda p, k: ff.grab_frame(p, 2.0 + (k + 0.5) / 24).astype(int)
    assert stats["underrun_frames"] == 0
    assert np.abs(grab(out, 1) - grab(plain, 1)).mean() > 2   # while it flies in, the old shot is still the background
    assert grab(out, 8).mean() > grab(plain, 8).mean() + 40     # the background arrives with a flash
    assert np.abs(grab(out, 14) - grab(plain, 14)).mean() < 2  # and then it is just the new shot


def test_pin_holds_the_subject_whole_then_cuts():
    old, new = np.full((90, 160, 3), 200, np.uint8), np.full((90, 160, 3), 20, np.uint8)
    alpha = np.zeros((90, 160), np.float32)
    alpha[20:70, 30:80] = 1.0
    for p in (0.05, 0.5, 0.95):  # no fading at any point: the subject whole, the new shot round it
        out = matte.wipe(old, new, alpha, p, "pin")
        assert out[45, 55, 0] == 200 and out[5, 150, 0] == 20
    assert matte.wipe(old, new, np.zeros((90, 160), np.float32), 0.5, "pin")[45, 55, 0] == 20  # no subject: a plain cut


def _dark_centre_x(image):
    ys, xs = np.nonzero(image[..., 0] < 110)
    return xs.mean()


def test_a_cut_out_spins_out_to_its_side_and_leaves():
    back = np.full((90, 160, 3), 200, np.uint8)
    subject = np.full((90, 160, 3), 20, np.uint8)
    alpha = np.zeros((90, 160), np.float32)
    alpha[30:60, 60:100] = 1.0
    assert matte.revolve(subject, alpha, back, 0.0, 0.1, True, 1.0)[45, 80, 0] < 60  # it starts in its place
    right = matte.revolve(subject, alpha, back, 0.4, 0.5, True, 1.0)
    left = matte.revolve(subject, alpha, back, 0.4, 0.5, True, -1.0)
    assert _dark_centre_x(right) > 80 + 15 and _dark_centre_x(left) < 80 - 15  # spin picks the side it flies to
    gone = matte.revolve(subject, alpha, back, 0.9, 1.0, True, 1.0)
    assert np.abs(gone.astype(int) - 200).max() <= 1  # and by the end it has left the frame


def test_a_cut_out_spins_in_from_off_the_frame_and_lands():
    back = np.full((90, 160, 3), 200, np.uint8)
    subject = np.full((90, 160, 3), 20, np.uint8)
    alpha = np.zeros((90, 160), np.float32)
    alpha[30:60, 60:100] = 1.0
    early = matte.revolve(subject, alpha, back, 0.0, 0.1, False, 1.0)
    assert np.abs(early.astype(int) - 200).max() <= 1  # it starts off the frame
    landed = matte.revolve(subject, alpha, back, 0.9, 1.0, False, 1.0)
    assert landed[45, 80, 0] < 60 and landed[10, 10, 0] > 150  # and lands in its place


def test_a_cut_out_flies_out_straight_without_turning():
    back = np.full((90, 160, 3), 200, np.uint8)
    subject = np.full((90, 160, 3), 20, np.uint8)
    alpha = np.zeros((90, 160), np.float32)
    alpha[40:50, 40:120] = 1.0  # a long flat bar
    mid = matte.revolve(subject, alpha, back, 0.4, 0.5, True, 1.0, steps=5, turn=0.0, rise=0.06, grow=0.12, shutter=0.45)
    ys, xs = np.nonzero(mid[..., 0] < 110)
    assert xs.mean() > 80 + 20  # it has moved off toward its side
    assert ys.max() - ys.min() < 16  # and is still a flat bar: it did not turn


def test_lead_brings_the_new_subject_first_then_its_background(project, left_half_subject):
    cut = three_slot_cut(project)
    cut["cuts"][1]["t"] = {"type": "matte", "frames": 6, "style": "lead"}
    assert manifest.validate(cut, project)[0] == []
    out, plain = project.root / "lead.mp4", project.root / "plain.mp4"
    stats = render(project, cut, out, 0.5, 20, "ultrafast", progress=QUIET)
    render(project, three_slot_cut(project), plain, 0.5, 20, "ultrafast", progress=QUIET)
    grab = lambda p, k: ff.grab_frame(p, 2.0 + (k + 0.5) / 24).astype(int)
    a, b = grab(out, 2), grab(plain, 2)
    half = a.shape[1] // 2
    assert stats["underrun_frames"] == 0
    assert np.abs(a[:, : half - 4] - b[:, : half - 4]).mean() < 3  # the incoming subject is already there
    assert np.abs(a[:, half + 4:] - b[:, half + 4:]).mean() > 2  # over what is left of the old shot
    assert np.abs(grab(out, 12) - grab(plain, 12)).mean() < 2  # then it is just the new shot
