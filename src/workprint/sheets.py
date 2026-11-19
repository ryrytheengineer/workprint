"""Pictures for looking at: contact sheets of the footage and storyboards of a cut.

These are how the editor (Claude, and the human) actually sees the material and the
film without playing video: a contact sheet per source for logging shots, a filmstrip
for a closer look at one shot, a storyboard of a rendered cut, and a sheet showing
both sides of every cut point.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import ff
from .manifest import timeline
from .titles import font_path

BG = (18, 18, 18)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path("sans")), size)


def _tile(frame: np.ndarray, width: int, lines: list[str]) -> Image.Image:
    h = int(round(frame.shape[0] * width / frame.shape[1]))
    image = Image.fromarray(cv2.cvtColor(cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
    label_h = 6 + 17 * len(lines)
    tile = Image.new("RGB", (width, h + label_h), BG)
    tile.paste(image, (0, 0))
    draw = ImageDraw.Draw(tile)
    for row, text in enumerate(lines):
        draw.text((6, h + 3 + 17 * row), text, font=_font(13), fill=(236, 232, 222) if row == 0 else (150, 150, 150))
    return tile


def _grid(tiles: list[Image.Image], cols: int, gap: int = 6) -> Image.Image:
    cols = max(1, min(cols, len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    w, h = tiles[0].size
    sheet = Image.new("RGB", (cols * w + (cols + 1) * gap, rows * h + (rows + 1) * gap), BG)
    for k, tile in enumerate(tiles):
        sheet.paste(tile, (gap + (k % cols) * (w + gap), gap + (k // cols) * (h + gap)))
    return sheet


def _tc(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def contact_sheets(project, sources: list[str] | None = None, cols: int = 5, tile: int = 384, per_page: int = 25) -> list[Path]:
    """One or more pages per source, one tile per shot, labelled with what was measured."""
    folder = project.log_dir / "sheets"
    folder.mkdir(parents=True, exist_ok=True)
    shots = project.shots()
    out = []
    for source in project.data["sources"]:
        if sources and source["id"] not in sources:
            continue
        mine = [s for s in shots if s["src"] == source["id"]]
        path = project.path_of(source)
        for page in range(0, len(mine), per_page):
            tiles = []
            for shot in mine[page:page + per_page]:
                frame = ff.grab_frame(path, shot["start"] + 0.4 * shot["dur"], tile)
                note = f"motion {shot['motion']:.1f}  cam {shot['camera']:.1f}"
                if shot.get("rating") is not None:
                    note += f"  rated {shot['rating']}"
                tiles.append(_tile(frame, tile, [f"{shot['id']}   {shot['dur']:.1f}s", f"{_tc(shot['start'])}-{_tc(shot['end'])}  {note}"]))
            if not tiles:
                continue
            suffix = f"-{page // per_page + 1}" if len(mine) > per_page else ""
            target = folder / f"{source['id']}{suffix}.jpg"
            _grid(tiles, cols).save(target, quality=88)
            out.append(target)
    return out


def filmstrip(project, shot: dict, count: int = 8, tile: int = 480, start: float | None = None, end: float | None = None) -> Path:
    """Evenly spaced frames across a shot (or a time range of its source) for a closer look."""
    source = project.source(shot["src"])
    a = shot["start"] if start is None else start
    b = shot["end"] if end is None else end
    times = [a + (b - a) * (k + 0.5) / count for k in range(count)]
    tiles = [_tile(ff.grab_frame(project.path_of(source), t, tile), tile, [f"{shot['id']}  @ {_tc(t)}"]) for t in times]
    folder = project.log_dir / "strips"
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "" if start is None and end is None else f"_{a:.1f}-{b:.1f}"
    target = folder / f"{shot['id']}{suffix}.jpg"
    _grid(tiles, 4).save(target, quality=88)
    return target


def read_small(path, width: int = 480) -> tuple[list[np.ndarray], float]:
    """Every frame of a (short) film at reduced size."""
    info = ff.probe(path)
    h = int(round(info["height"] * width / info["width"] / 2)) * 2
    frames = []
    with ff.FrameReader(path, 0.0, info["fps"], (width, h), matrix="bt709", scaler="area") as reader:
        while True:
            frame = reader.read()
            if frame is None:
                break
            frames.append(frame.copy())
    return frames, info["fps"]


def storyboard(cut: dict, frames: list[np.ndarray], target: Path, cols: int = 6, tile: int = 320) -> Path:
    """One frame from the middle of every slot of the rendered film, in order."""
    tiles = []
    fps = cut["format"]["fps"]
    for slot in timeline(cut):
        entry = slot["cut"]
        mid = min(len(frames) - 1, (slot["f0"] + slot["f1"]) // 2)
        what = entry.get("src", "card") + (f" @{entry['in']:.1f}" if "in" in entry else "")
        tiles.append(_tile(frames[mid], tile, [f"{entry.get('id', '')}  {_tc(slot['f0'] / fps)}  {(slot['f1'] - slot['f0']) / fps:.2f}s", what]))
    target.parent.mkdir(parents=True, exist_ok=True)
    _grid(tiles, cols).save(target, quality=86)
    return target


def cut_pairs(cut: dict, frames: list[np.ndarray], target: Path, cols: int = 4, tile: int = 240) -> Path:
    """Both sides of every cut point: the last frame out and the first frame in."""
    fps = cut["format"]["fps"]
    tiles = []
    for slot in timeline(cut)[1:]:
        f = min(slot["f0"], len(frames) - 1)
        pair = np.hstack([frames[max(0, f - 1)], frames[f]])
        tiles.append(_tile(pair, tile * 2, [f"into {slot['cut'].get('id', '')} at {_tc(f / fps)} (frame {f})"]))
    if not tiles:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    _grid(tiles, cols).save(target, quality=84)
    return target
