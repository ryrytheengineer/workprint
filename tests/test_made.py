"""Made frames: footage on a screen in a still, and cut-out cards.

The stills and pictures here are flat colours with known geometry, so where a picture lands,
which way round it is, and what covers what can be checked exactly. The subject model for
cut-outs is stood in for; the model itself is tested only where it is installed.
"""
import cv2
import numpy as np
import pytest

from workprint import cards, cli, ff, matte, screen

WALL, CASE, GLASS = (150, 150, 150), (90, 90, 90), (22, 22, 22)
CORNERS = [(200, 100), (440, 110), (436, 290), (204, 300)]   # a screen seen slightly from one side


def room():
    """A wall, a casing, and a dark screen in it."""
    image = np.full((400, 640, 3), WALL, np.uint8)
    cv2.rectangle(image, (160, 60), (480, 340), CASE, -1)
    cv2.fillConvexPoly(image, np.int32(CORNERS), GLASS)
    return image


def halves():
    """A picture that is green on the left and red on the right, with a blue band along the top."""
    pic = np.zeros((240, 320, 3), np.uint8)
    pic[:, :160] = (0, 255, 0)
    pic[:, 160:] = (0, 0, 255)
    pic[:40] = (255, 0, 0)
    return pic


def test_the_screen_is_found_inside_its_casing():
    guess = screen.find(room())
    assert guess is not None and guess["kind"] == "dark" and guess["fill"] > 0.9
    for (x, y), (gx, gy) in zip(CORNERS, guess["corners"]):   # the screen, not the casing round it, and in the same order
        assert abs(x - gx) < 8 and abs(y - gy) < 8


def test_corners_can_be_given_in_any_order():
    shuffled = [CORNERS[2], CORNERS[0], CORNERS[3], CORNERS[1]]
    assert np.allclose(screen.order_corners(shuffled), np.float32(CORNERS))


def test_a_picture_lands_on_the_screen_the_right_way_round():
    scr = screen.Screen(room(), CORNERS, radius=0.0, look="none", spill=0.0)
    out = scr.show(halves())
    assert np.argmax(out[200, 260]) == 1 and out[200, 260, 1] > 200      # left of the screen: green
    assert np.argmax(out[200, 390]) == 2 and out[200, 390, 2] > 200      # right: red
    assert np.argmax(out[115, 320]) == 0                                 # along the top: blue
    assert np.allclose(out[30, 30], WALL) and np.allclose(out[200, 170], CASE)   # nothing outside it moved


def test_the_dark_screen_and_rounded_corners():
    scr = screen.Screen(room(), CORNERS, radius=0.2, look="none", spill=0.0)
    lit, dark = scr.show(np.full((240, 320, 3), 255, np.uint8)), scr.show(None)
    assert lit[200, 320].min() > 240 and dark[200, 320].max() < 60
    assert np.allclose(lit[103, 203], GLASS, atol=3)        # a rounded corner leaves the still showing there
    with pytest.raises(ValueError):
        screen.Screen(room(), CORNERS, look="plasma")


def test_the_picture_lights_what_is_round_the_screen():
    white = np.full((240, 320, 3), 255, np.uint8)
    lit = screen.Screen(room(), CORNERS, look="none", spill=0.8).show(white)
    unlit = screen.Screen(room(), CORNERS, look="none", spill=0.0).show(white)
    near, far = (200, 190), (30, 30)                         # on the casing beside the glass; a corner of the wall
    assert lit[near].mean() > unlit[near].mean() + 15
    assert abs(lit[far].mean() - unlit[far].mean()) < 1.0
    assert np.allclose(unlit[near], CASE)


def test_a_tube_softens_and_scans_the_picture():
    grey = np.full((240, 320, 3), 128, np.uint8)
    crt = screen.Screen(room(), CORNERS, look="crt", work=3.0)
    rows = crt.tube(grey)[:, crt.rw // 2, 1]
    assert rows.max() - rows.min() > 8                       # scanlines
    assert np.ptp(screen.Screen(room(), CORNERS, look="flat", work=3.0).tube(grey)[:, 50, 1]) < 2
    opening = crt.tube(grey, power=0.1)
    assert opening[5].max() < 10 and opening[crt.rh // 2].min() > 100   # switching on: a bright line across the middle


def test_frames_switch_on_and_push_in():
    def pictures():
        while True:
            yield np.full((240, 320, 3), (0, 255, 0), np.uint8)
    shots = list(screen.frames(room(), CORNERS, pictures(), 12, (320, 180), 24.0, push=(1.0, 1.6), look="none", spill=0.0))
    assert len(shots) == 12 and all(f.shape == (180, 320, 3) and f.dtype == np.uint8 for f in shots)
    green = [int(((f[..., 1] > 200) & (f[..., 2] < 80)).sum()) for f in shots]
    assert green[0] == 0 and green[-1] > 0                   # dark before it switches on
    on = list(screen.frames(room(), CORNERS, pictures(), 12, (320, 180), 24.0, push=(1.0, 1.6), power_on=False, look="none", spill=0.0))
    area = [int(((f[..., 1] > 200) & (f[..., 2] < 80)).sum()) for f in on]
    assert area[-1] > 2.0 * area[0] > 0                      # the screen fills more of the frame as the camera goes in
    assert area[3] - area[0] > area[-1] - area[8]            # and the move starts fast and settles
    held = list(screen.frames(room(), CORNERS, iter([halves()]), 4, (320, 180), 24.0, push=(1.0, 1.0), power_on=False, look="none"))
    assert np.abs(held[3].astype(int) - held[0].astype(int)).mean() < 1.0   # one picture, held once the clip runs out


def test_screen_commands_find_then_make(project, capsys):
    still = project.root / "room.png"
    cv2.imwrite(str(still), room())
    assert cli.main(["-p", str(project.root), "screen", "find", str(still)]) == 0
    out = capsys.readouterr().out
    assert "--corners" in out and (project.root / "review" / "screen-room.jpg").exists()
    before = len(project.data["sources"])
    corners = " ".join(f"{x},{y}" for x, y in CORNERS)
    assert cli.main(["-p", str(project.root), "screen", "make", str(still), "--corners", corners, "--clip", "A001", "--in", "0.2", "--dur", "1.0",
                     "--look", "flat"]) == 0
    assert "added as" in capsys.readouterr().out
    made = project.root / "made" / "screen-room-A001.mp4"
    fresh = type(project)(project.root)
    assert len(fresh.data["sources"]) == before + 1 and abs(ff.probe(made)["duration"] - 1.0) < 0.1
    assert ff.grab_frame(made, 0.7).std() > 20
    assert cli.main(["-p", str(project.root), "screen", "make", str(still), "--clip", "A001"]) == 2   # no corners given


# ---- cut-out cards --------------------------------------------------------------------------------
@pytest.fixture()
def left_half_subject(monkeypatch):
    """Stand in for the model: the subject is the left half of the frame."""
    def fake(frame):
        alpha = np.zeros(frame.shape[:2], np.float32)
        alpha[:, :frame.shape[1] // 2] = 1.0
        return alpha
    monkeypatch.setattr(matte, "subject", fake)
    monkeypatch.setattr(matte, "tools", lambda: {"runtime": True, "model": True})


def blue():
    while True:
        yield np.full((180, 320, 3), (255, 0, 0), np.uint8)


def test_words_come_in_small_first_then_large():
    assert cards.tokens(["SOLVING", "PROBLEMS NOW."], "Life can't") == ["Life", "can't", "SOLVING", "PROBLEMS", "NOW."]
    placed = cards.layout((640, 360), ["SOLVING", "PROBLEMS NOW."], "Life can't")["words"]
    assert [p[2] for p in placed] == ["Life", "can't", "SOLVING", "PROBLEMS", "NOW."] and [p[4] for p in placed] == [False, False, True, True, True]
    assert placed[0][1] < placed[2][1] < placed[3][1]        # small line above, large lines stacked
    assert all(p[0] >= 0 for p in placed)


def test_words_arrive_on_time_and_pass_behind_the_subject(left_half_subject):
    shots = list(cards.frames(blue(), 24, (640, 360), 24.0, ["WWWWWWWW"], times=[0.5], place="centre", scale=1.0, push=0.0, flash=False))
    assert len(shots) == 24

    def ink(frame):
        return (frame.max(axis=2) < 60)
    subject = (shots[0][..., 0] > 200) & (shots[0][..., 2] < 60)             # solid blue: where the subject stands
    assert subject.sum() > 0.2 * subject.size
    assert ink(shots[6]).sum() == 0                                          # before its time the word is not there
    assert ink(shots[20]).sum() > 500                                        # after, it is
    assert (ink(shots[20]) & subject).sum() == 0                             # and none of it is drawn over the subject
    cols = np.flatnonzero(ink(shots[20]).any(0))
    both = np.flatnonzero(subject.any(0))
    assert cols.min() < both.min() and cols.max() > both.max()               # the word runs on behind them, out both sides


def test_a_large_word_lands_with_an_overshoot(left_half_subject):
    shots = list(cards.frames(blue(), 12, (640, 360), 24.0, ["WWWW"], times=[0.0], place="left", scale=1.0, push=0.0, flash=False))
    dark = [int((f.max(axis=2) < 60).sum()) for f in shots]
    assert dark[0] > dark[8] * 1.05 and abs(dark[8] - dark[11]) < 0.01 * dark[8]   # bigger as it lands, then still


def test_the_card_checks_its_inputs(left_half_subject):
    with pytest.raises(ValueError):
        list(cards.frames(blue(), 2, (320, 180), 24.0, ["ONE", "TWO"], times=[0.1]))
    with pytest.raises(ValueError):
        list(cards.frames(blue(), 2, (320, 180), 24.0, ["ONE"], place="above"))


def test_cutout_command_adds_a_card_to_the_footage(project, left_half_subject, capsys):
    before = len(project.data["sources"])
    assert cli.main(["-p", str(project.root), "cutout", "--clip", "A001", "--in", "0.2", "--dur", "1.0", "--small", "just the", "--big", "WORD",
                     "--times", "0.1,0.2,0.4"]) == 0
    assert "added as" in capsys.readouterr().out
    made = next((project.root / "made").glob("cutout-A001-*.mp4"))
    assert len(type(project)(project.root).data["sources"]) == before + 1 and abs(ff.probe(made)["duration"] - 1.0) < 0.1
    frame = ff.grab_frame(made, 0.8)
    assert (frame.min(axis=2) > 235).mean() > 0.2            # a pale card behind
    assert cli.main(["-p", str(project.root), "cutout", "--clip", "A001", "--big", "A B", "--times", "0.1"]) == 2   # two words, one time


def test_cutout_needs_the_matte_tools(project, monkeypatch, capsys):
    monkeypatch.setattr(matte, "tools", lambda: {"runtime": False, "model": False})
    assert cli.main(["-p", str(project.root), "cutout", "--clip", "A001", "--big", "WORD"]) == 2
    assert "matte setup" in capsys.readouterr().err
