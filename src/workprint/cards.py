"""Cut-out cards: a subject lifted off their background and set on a plain card, with type behind them.

The card is drawn in three layers: the plain background, the words, and the subject cut out
of the clip on top, so the words pass behind the subject. Words appear one at a time, at the
times given, and the large ones land with a small overshoot. Needs the matte tools
(``workprint matte setup``), which find the subject in each frame.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import matte
from .titles import font_path

PLACES = ("right", "left", "centre")


def _hex(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _font(name: str, size: float, weight: int | None = None) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(font_path(name)), max(4, int(round(size))))
    if weight:
        try:  # variable fonts only
            axes = font.get_variation_axes()
            names = [a["name"].decode() if isinstance(a["name"], bytes) else str(a["name"]) for a in axes]
            font.set_variation_by_axes([float(weight) if n.lower() in ("weight", "wght") else a["default"] for n, a in zip(names, axes)])
        except Exception:
            pass
    return font


def tokens(big: list[str], small: str | None) -> list[str]:
    """The words of a card in the order they appear: the small line first, then each large line."""
    return (small.split() if small else []) + [w for line in big for w in line.split()]


def layout(size: tuple[int, int], big: list[str], small: str | None, place: str = "right") -> dict:
    """Where every word sits. Returns fonts and one (x, y, word, font, large?) entry per word, in ``tokens`` order."""
    w, h = size
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    margin = 0.055 * w
    limit = (0.9 if place == "centre" else 0.86) * w
    big_size = min(0.31 * h, 0.62 * h / max(1, len(big)) / 1.02)
    for _ in range(3):
        f_big = _font("display", big_size)
        widest = max((probe.textlength(line, font=f_big) for line in big), default=0.0)
        if widest <= limit or big_size < 12:
            break
        big_size *= limit / widest
    f_big = _font("display", big_size)
    f_small = _font("serif-italic", 0.095 * h)
    line_h = big_size * 1.0
    block = line_h * len(big)
    small_h = 0.13 * h if small else 0.0
    top = (h - block - small_h) / 2 + small_h * 0.55 if place == "centre" else 0.14 * h + small_h
    out = []

    def run(text: str, font, y: float, large: bool):
        total = probe.textlength(text, font=font)
        x = (w - total) / 2 if place == "centre" else (w - margin - total if place == "left" else margin)
        for word in text.split():
            out.append((float(x), float(y), word, font, large))
            x += probe.textlength(word + " ", font=font)

    if small:
        run(small, f_small, top - small_h, False)
    for i, line in enumerate(big):
        asc = f_big.getbbox("H")[1]   # the gap above cap height, so lines sit by their ink
        run(line, f_big, top + i * line_h - asc * 0.6, True)
    return {"words": out, "big": f_big, "small": f_small}


def _draw_words(size: tuple[int, int], words: list, times: list[float], now: float, ink: tuple[int, int, int]) -> np.ndarray:
    """BGRA layer of the words whose time has come. A large word overshoots for the first 0.14 s."""
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for (x, y, word, font, large), at in zip(words, times):
        if at > now:
            continue
        age = now - at
        s = 1.0 + 0.10 * (1 - min(1.0, age / 0.14)) ** 3 if large else 1.0
        if s > 1.004:
            box = font.getbbox(word)
            tw, th = box[2] + 8, box[3] + 8
            tile = Image.new("RGBA", (int(tw), int(th)), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((0, 0), word, font=font, fill=ink + (255,))
            tile = tile.resize((int(tw * s), int(th * s)), Image.LANCZOS)
            layer.alpha_composite(tile, (int(x - tw * (s - 1) / 2), int(y - th * (s - 1) / 2)))
        else:
            draw.text((x, y), word, font=font, fill=ink + (255,))
    a = np.array(layer)
    return a[..., [2, 1, 0, 3]]


def _over(canvas: np.ndarray, rgba: np.ndarray, x: float, y: float) -> None:
    """Alpha-blend a BGRA image onto a BGR canvas at x, y, clipped at the edges."""
    h, w = rgba.shape[:2]
    x, y = int(round(x)), int(round(y))
    x0, y0, x1, y1 = max(0, x), max(0, y), min(canvas.shape[1], x + w), min(canvas.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    part = rgba[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    a = part[..., 3:4] / 255.0
    canvas[y0:y1, x0:x1] = (part[..., :3] * a + canvas[y0:y1, x0:x1] * (1 - a) + 0.5).astype(np.uint8)


def cut_out(frame: np.ndarray, alpha: np.ndarray, scale: float, ignore=None) -> np.ndarray:
    """The subject as a BGRA image, scaled. ``ignore`` is rectangles (x0, y0, x1, y1 as fractions) never to keep: a logo, a bug."""
    a = np.clip((alpha - 0.08) / 0.84, 0.0, 1.0)
    h, w = a.shape
    for x0, y0, x1, y1 in ignore or []:
        a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 0.0
    big = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    if scale > 1.3:
        big = cv2.addWeighted(big, 1.5, cv2.GaussianBlur(big, (0, 0), 1.1 * scale), -0.5, 0)
    soft = cv2.resize(a, (big.shape[1], big.shape[0]), interpolation=cv2.INTER_LINEAR)
    return np.dstack([big, (soft * 255).astype(np.uint8)])


def frames(pictures, count: int, size: tuple[int, int], fps: float, big: list[str], small: str | None = None,
           times: list[float] | None = None, bg: str = "#fafafa", ink: str = "#111111", place: str = "right",
           scale: float = 1.15, push: float = 0.04, flash: bool = True, ignore=None):
    """Yield ``count`` frames (uint8 BGR, ``size``) of the card.

    ``pictures``: BGR frames of the clip at ``fps``; the last is held if they run out. ``big``: the large lines.
    ``small``: one line of small italic words above them. ``times``: seconds from the start at which each word
    appears, in ``tokens`` order (all at once if omitted). ``place``: where the subject stands. ``scale``: the
    clip's frame height as a multiple of the card's, so 1.15 lets the subject run off the bottom a little.
    """
    if place not in PLACES:
        raise ValueError(f"unknown place {place!r} (known: {', '.join(PLACES)})")
    w, h = size
    words = layout(size, big, small, place)["words"]
    times = [0.0] * len(words) if times is None else [float(t) for t in times]
    if len(times) != len(words):
        raise ValueError(f"{len(words)} words on the card but {len(times)} times given")
    paper, ink_rgb = _hex(bg)[::-1], _hex(ink)
    tracker = matte.Tracker(0.5)
    pictures = iter(pictures)
    last, offset = None, None
    anchor = {"right": 0.72, "left": 0.28, "centre": 0.5}[place]
    for i in range(count):
        t = i / fps
        nxt = next(pictures, None)
        last = nxt if nxt is not None else last
        canvas = np.full((h, w, 3), paper, np.uint8)
        _over(canvas, _draw_words(size, words, times, t, ink_rgb), 0, 0)
        if last is not None:
            factor = scale * h / last.shape[0]
            alpha = tracker.of(last)
            cut = cut_out(last, alpha, factor, ignore)
            if offset is None:   # stand the subject where asked, by where their weight is in the first frame
                column = alpha.sum(0)
                centre = float((column * np.arange(len(column))).sum() / max(1e-6, column.sum())) if column.sum() > 0 else last.shape[1] / 2
                offset = anchor * w - centre * factor
            # taller than the card: keep more of the top (the head) than of the bottom
            _over(canvas, cut, offset, (h - cut.shape[0]) * (0.35 if cut.shape[0] > h else 1.0))
        if push:
            s = 1.0 + push * i / max(1, count - 1)
            canvas = cv2.warpAffine(canvas, np.float32([[s, 0, w / 2 * (1 - s)], [0, s, h / 2 * (1 - s)]]), (w, h),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if flash and i < 2:
            canvas = cv2.addWeighted(canvas, 0.4, np.full_like(canvas, 255), 0.6, 0)
        yield canvas
