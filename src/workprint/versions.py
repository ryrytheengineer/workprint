"""Versions: the same cut in another shape.

A finished 16:9 cut becomes a 9:16, 4:5 or 1:1 film by rendering every slot through the
same pipeline at a new frame size. What changes per shot is where the new frame sits on
the source: its *focus*. ``workprint reframe`` proposes a focus for every slot by
measuring where the detail and the movement are, writes it into the cut (for example
``focus_9x16``) and draws a review sheet. The editor looks at the sheet and corrects the
ones it got wrong; the proposal is a starting point, not a judgement about the subject.
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from . import ff
from .manifest import source_span, timeline


def parse(aspect: str) -> tuple[str, float]:
    """'9:16', '9x16' or '9/16' -> ('9x16', 0.5625)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*", str(aspect))
    if not m or float(m.group(2)) == 0:
        raise ValueError(f"aspect should look like 9:16, 4:5 or 1:1, not {aspect!r}")
    a, b = m.group(1), m.group(2)
    return f"{a}x{b}", float(a) / float(b)


def size_for(fmt: dict, ratio: float) -> tuple[int, int]:
    """Frame size of a version: the cut's short side is kept."""
    short = min(fmt["width"], fmt["height"])
    even = lambda v: int(round(v / 2.0)) * 2
    return (short, even(short / ratio)) if ratio < 1.0 else (even(short * ratio), short)


def _window(profile: np.ndarray, frac: float) -> float:
    """Where along an axis a window covering ``frac`` of it holds the most, as 0..1 of the slack. Leans to the centre."""
    n = len(profile)
    size = max(1, int(round(frac * n)))
    if size >= n:
        return 0.5
    total = np.cumsum(np.r_[0.0, profile])
    sums = total[size:] - total[:-size]
    centre = (np.arange(len(sums)) + size / 2.0) / n
    best = int(np.argmax(sums * (1.0 - 0.3 * np.abs(centre - 0.5) * 2.0)))
    return round(best / max(1, n - size), 2)


def _samples(project, entry: dict, frames: int, fps: float, at=(0.15, 0.5, 0.85)) -> list[np.ndarray]:
    source = project.source(entry["src"])
    a, b = source_span(entry, frames, fps)
    b = min(b, source["duration"] - 1.0 / fps)
    return [ff.grab_frame(project.path_of(source), max(0.0, a + (b - a) * k), 320) for k in at]


def focus_of(project, entry: dict, frames: int, fps: float, ratio: float, at=(0.15, 0.5, 0.85)) -> list[float] | None:
    """A proposed focus for one slot, or None when the source already has the version's shape."""
    source = project.source(entry["src"])
    shape = source["width"] / source["height"]
    if abs(shape - ratio) < 0.01:
        return None
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in _samples(project, entry, frames, fps, at)]
    detail = sum(cv2.GaussianBlur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (0, 0), 4) for g in grays)
    motion = sum(cv2.GaussianBlur(cv2.absdiff(a, b), (0, 0), 4) for a, b in zip(grays, grays[1:]))
    weight = detail / (detail.mean() + 1e-6)
    if motion.mean() > 0.5:  # something moves: it matters more than texture
        weight = weight + 1.5 * motion / motion.mean()
    old = entry.get("focus") or (0.5, 0.5)
    if ratio < shape:  # the version is narrower than the source: choose left-right
        return [_window(weight.sum(0), ratio / shape), float(old[1])]
    return [float(old[0]), _window(weight.sum(1), shape / ratio)]


def propose(project, cut: dict, tag: str, ratio: float, only: list[str] | None = None, redo: bool = False,
            follow: bool = False) -> list[tuple[str, list[float]]]:
    """Write a focus for this version into every slot that lacks one. Returns what was set.

    With ``follow``, the start and the end of each shot are measured separately; where they differ, the frame
    travels from one to the other during the shot (``focus_9x16_to``).
    """
    fps = cut["format"]["fps"]
    key, done = f"focus_{tag}", []
    for slot in timeline(cut):
        entry = slot["cut"]
        if "src" not in entry or entry.get("fit") == "contain" or (only and entry.get("id") not in only):
            continue
        if key in entry and not redo and not only:
            continue
        focus = focus_of(project, entry, slot["f1"] - slot["f0"], fps, ratio)
        if focus is not None:
            entry.pop(key + "_to", None)
            if follow and slot["f1"] - slot["f0"] >= 12:
                first = focus_of(project, entry, slot["f1"] - slot["f0"], fps, ratio, (0.05, 0.15, 0.25))
                last = focus_of(project, entry, slot["f1"] - slot["f0"], fps, ratio, (0.75, 0.85, 0.95))
                if max(abs(first[0] - last[0]), abs(first[1] - last[1])) >= 0.08:
                    focus, entry[key + "_to"] = first, last
            entry[key] = focus
            done.append((entry.get("id", "?"), focus + (["->"] + entry[key + "_to"] if key + "_to" in entry else [])))
    return done


def sheet(project, cut: dict, tag: str, ratio: float, target: Path, cols: int = 6, tile: int = 300) -> Path:
    """One frame per slot with the version's frame drawn on it."""
    fps = cut["format"]["fps"]
    key, cells = f"focus_{tag}", []
    for slot in timeline(cut):
        entry = slot["cut"]
        if "src" not in entry:
            continue
        frame = _samples(project, entry, slot["f1"] - slot["f0"], fps)[1]
        h, w = frame.shape[:2]
        shape = w / h
        fx, fy = entry.get(key) or entry.get("focus") or (0.5, 0.5)
        cw, ch = (int(h * ratio), h) if ratio < shape else (w, int(w / ratio))
        x0, y0 = int((w - cw) * fx), int((h - ch) * fy)
        shade = (frame * 0.35).astype(np.uint8)
        shade[y0:y0 + ch, x0:x0 + cw] = frame[y0:y0 + ch, x0:x0 + cw]
        cv2.rectangle(shade, (x0, y0), (x0 + cw - 1, y0 + ch - 1), (255, 255, 255), 1)
        cell = cv2.resize(shade, (tile, int(tile * h / w)), interpolation=cv2.INTER_AREA)
        cv2.putText(cell, f"{entry.get('id', '')} {fx:.2f},{fy:.2f}", (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(cell, f"{entry.get('id', '')} {fx:.2f},{fy:.2f}", (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(cell)
    if not cells:
        raise ValueError("the cut has no footage to reframe")
    ch_ = max(c.shape[0] for c in cells)
    rows = []
    for i in range(0, len(cells), cols):
        row = [cv2.copyMakeBorder(c, 0, ch_ - c.shape[0], 0, 0, cv2.BORDER_CONSTANT) for c in cells[i:i + cols]]
        row += [np.zeros((ch_, tile, 3), np.uint8)] * (cols - len(row))
        rows.append(np.hstack(row))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return target
