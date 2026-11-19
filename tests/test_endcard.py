"""Logos as picture elements and the end card layout."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from workprint import check, cli, ff, manifest, titles
from workprint.render import plan, render
from tests.test_voice import three_slot_cut

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 60"><rect x="0" y="10" width="300" height="40" fill="#ffffff"/></svg>')


def make_logo(path):
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((10, 10, 190, 190), fill=(255, 255, 255, 255))
    image.save(path)
    return path


def test_a_picture_keeps_its_shape_and_can_be_tinted(tmp_path):
    make_logo(tmp_path / "mark.png")
    pic = titles.Picture({"image": "mark.png", "style": {"height": 0.25, "pos": [0.5, 0.5]}}, 640, 360, tmp_path)
    x0, y0, x1, y1 = pic.box
    assert (x1 - x0, y1 - y0) == (90, 90) and abs((x0 + x1) / 2 - 320) <= 1
    frame = np.zeros((360, 640, 3), np.uint8)
    pic.draw(frame, 1.0)
    assert frame[180, 320].min() > 240 and frame[y0 + 2, x0 + 2].max() == 0  # disc drawn, transparent corner untouched
    red = titles.Picture({"image": "mark.png", "style": {"width": 0.2, "color": "#ff0000"}}, 640, 360, tmp_path)
    frame[:] = 0
    red.draw(frame, 1.0)
    assert tuple(frame[180, 320]) == (0, 0, 255)
    with pytest.raises(FileNotFoundError):
        titles.Picture({"image": "nope.png"}, 640, 360, tmp_path)


@pytest.mark.skipif(titles.svg_tool() is None, reason="no SVG converter installed")
def test_svg_logos_are_drawn_at_the_size_asked(tmp_path):
    (tmp_path / "word.svg").write_text(SVG)
    image = titles.load_image(tmp_path / "word.svg", 600)
    assert image.size == (600, 120) and image.getpixel((300, 60))[3] == 255 and image.getpixel((300, 5))[3] == 0


def test_the_end_card_lays_out_title_and_logos(project):
    root = project.root
    make_logo(root / "mark.png")
    make_logo(root / "word.png")
    project.save_cut(three_slot_cut(project), "three slots")
    before = plan(project, project.cut(), 0.5, 30, "ultrafast")["paths"]
    assert cli.main(["-p", str(root), "endcard", "--text", "NEVER|THE SAME", "--logo", "mark.png", "--wordmark", "word.png", "--dur", "2"]) == 0
    cut = project.cut()
    card = [t for t in cut["titles"] if t.get("role") == "endcard"]
    assert cut["duration"] == 8.0 and cut["cuts"][-1]["at"] == 6.0 and "card" in cut["cuts"][-1]
    assert [bool(t.get("image")) for t in card] == [False, True, True] and card[0]["text"] == "NEVER\nTHE SAME"
    assert card[1]["style"]["pos"][0] < 0.5 < card[2]["style"]["pos"][0] and card[1]["style"]["pos"][1] == card[2]["style"]["pos"][1]
    job = plan(project, cut, 0.5, 30, "ultrafast")
    assert job["paths"][:3] == before and len(job["paths"]) == 4  # the film before the card keeps its chunks
    out = root / "card.mp4"
    render(project, cut, out, 0.5, 30, "ultrafast", progress=lambda *_: None)
    frame = ff.grab_frame(out, 7.0)
    h, w = frame.shape[:2]
    assert frame[5, 5].max() < 12 and frame[int(0.25 * h):int(0.6 * h)].max() > 200  # black card, title in the upper part
    mark = titles.Picture(card[1], w, h, root).box
    assert frame[(mark[1] + mark[3]) // 2, (mark[0] + mark[2]) // 2].min() > 180
    report = check.check(project, cut, out, write_review=False)
    assert report["verdict"] != "FAIL" and not any("safe margin" in f["text"] for f in report["findings"])
    assert cli.main(["-p", str(root), "endcard", "--text", "RETURN", "--dur", "2"]) == 0  # doing it again replaces the card
    cut = project.cut()
    assert cut["duration"] == 8.0 and len([t for t in cut["titles"] if t.get("role") == "endcard"]) == 1 and len(cut["cuts"]) == 4
    cut["titles"].append({"id": "t099", "at": 6.2, "dur": 1.0, "image": "missing.png"})
    assert any("missing.png" in e for e in manifest.validate(cut, project)[0])
