"""Words behind a subject, and photographs as shots. The model itself is tested only where it is installed."""
import cv2
import numpy as np
import pytest

from workprint import cli, ff, manifest, matte
from workprint.render import RenderError, plan, render
from tests.test_voice import three_slot_cut


@pytest.fixture()
def left_half_subject(monkeypatch):
    """Stand in for the model: the subject is the left half of the frame."""
    def fake(frame):
        alpha = np.zeros(frame.shape[:2], np.float32)
        alpha[:, :frame.shape[1] // 2] = 1.0
        return alpha
    monkeypatch.setattr(matte, "subject", fake)
    monkeypatch.setattr(matte, "tools", lambda: {"runtime": True, "model": True})


def captioned(project, behind):
    cut = three_slot_cut(project)
    cut["captions"] = [{"id": "k001", "at": 2.2, "dur": 1.4, "text": "WILL", "style": "punch", "set": {"behind": True, "dim": 0.0} if behind else {"dim": 0.0}}]
    return cut


def test_words_can_sit_behind_the_subject(project, left_half_subject):
    quiet = lambda *_: None
    plain, front, back = (project.root / n for n in ("p.mp4", "f.mp4", "b.mp4"))
    render(project, three_slot_cut(project), plain, 0.5, 14, "ultrafast", progress=quiet)
    render(project, captioned(project, False), front, 0.5, 14, "ultrafast", progress=quiet)
    cut = captioned(project, True)
    assert plan(project, cut, 0.5, 14, "ultrafast")["todo"] == [1]  # only the chunk under the words
    render(project, cut, back, 0.5, 14, "ultrafast", progress=quiet)
    p, f, b = (ff.grab_frame(x, 3.0).astype(int) for x in (plain, front, back))
    w = p.shape[1]
    left, right = slice(0, w // 2 - 8), slice(w // 2 + 8, w)
    assert np.abs(f[:, left] - p[:, left]).max() > 100 and np.abs(f[:, right] - p[:, right]).max() > 100  # in front: words everywhere
    assert np.abs(b[:, left] - p[:, left]).mean() < 1.5  # behind: the subject (left half) covers them
    assert np.abs(b[:, right] - f[:, right]).mean() < 1.5  # and they show where the subject is not


def test_rendering_words_behind_needs_the_tools(project, monkeypatch):
    monkeypatch.setattr(matte, "tools", lambda: {"runtime": False, "model": False})
    with pytest.raises(RenderError, match="matte setup"):
        render(project, captioned(project, True), project.root / "x.mp4", 0.5, 30, "ultrafast", progress=lambda *_: None)
    assert cli.main(["matte", "setup"]) == 1  # says what it would install and stops


def photo(path):
    rng = np.random.default_rng(4)
    image = cv2.GaussianBlur(rng.integers(0, 255, (600, 900, 3), dtype=np.uint8), (0, 0), 9)
    cv2.circle(image, (300, 300), 120, (40, 200, 240), -1)
    cv2.imwrite(str(path), image)
    return path


def test_a_photograph_becomes_a_shot(project, tmp_path, left_half_subject):
    before = len(project.data["sources"])
    for move in ("drift", "parallax"):
        assert cli.main(["-p", str(project.root), "still", str(photo(tmp_path / "pic.png")), "--dur", "1.5", "--move", move]) == 0
    fresh = type(project)(project.root)
    assert len(fresh.data["sources"]) == before + 2
    fmt = fresh.format
    for source in fresh.data["sources"][-2:]:
        info = ff.probe(fresh.path_of(source))
        assert (info["width"], info["height"]) == (fmt["width"], fmt["height"]) and abs(info["duration"] - 1.5) < 0.1
        first, last = ff.grab_frame(fresh.path_of(source), 0.05), ff.grab_frame(fresh.path_of(source), 1.4)
        assert np.abs(first.astype(int) - last.astype(int)).mean() > 2  # it moves
        assert first.min(axis=2).mean() > 5  # no black borders
    frames = list(matte.still_frames(cv2.imread(str(tmp_path / "pic.png")), 320, 180, 3, "push"))
    assert len(frames) == 3 and frames[0].shape == (180, 320, 3)
    with pytest.raises(matte.MatteError):
        next(matte.still_frames(frames[0], 320, 180, 3, "spin"))


@pytest.mark.skipif(not all(matte.tools().values()), reason="the optional matte model is not installed")
def test_the_model_finds_an_obvious_subject():
    image = np.full((360, 640, 3), 20, np.uint8)
    cv2.circle(image, (320, 180), 110, (60, 200, 250), -1)
    alpha = matte.subject(image)
    truth = np.zeros((360, 640), bool)
    cv2.circle(truth.view(np.uint8), (320, 180), 110, 1, -1)
    found = alpha > 0.5
    assert (found & truth).sum() / (found | truth).sum() > 0.85
