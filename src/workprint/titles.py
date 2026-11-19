"""Typography: titles rendered once to an alpha mask, then composited per frame.

Three open-licensed typefaces ship with Workprint (see THIRD_PARTY.md); any font
file on disk can be used by giving its path as ``style.font``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .look import hex_bgr

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = {"display": "ArchivoBlack-Regular.ttf", "serif": "InstrumentSerif-Regular.ttf", "sans": "Inter-Variable.ttf"}
DEFAULT_STYLE = {"font": "display", "size": 0.11, "tracking": 0.0, "leading": 1.08, "color": "#f4f1ea", "pos": [0.5, 0.5],
                 "align": "center", "width": 0.84, "upper": False, "shadow": 0.0, "opacity": 1.0}
SS = 2  # supersampling factor for edge quality


def font_path(name: str) -> Path:
    if name in FONTS:
        return FONT_DIR / FONTS[name]
    path = Path(name).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"font not found: {name} (bundled: {', '.join(FONTS)})")
    return path


def _advances(font: ImageFont.FreeTypeFont, text: str, tracking_px: float) -> tuple[list[float], float]:
    """Pen position of each character and the total width, honouring kerning and tracking."""
    xs, x = [], 0.0
    for i, ch in enumerate(text):
        xs.append(x)
        pair = text[i:i + 2]
        adv = font.getlength(pair) - font.getlength(pair[1]) if len(pair) == 2 else font.getlength(ch)
        x += adv + (tracking_px if i < len(text) - 1 else 0.0)
    return xs, x


class Title:
    """A rendered title: an alpha mask, its colour and where it sits in the frame."""

    def __init__(self, spec: dict, width: int, height: int):
        style = {**DEFAULT_STYLE, **(spec.get("style") or {})}
        text = str(spec["text"])
        lines = (text.upper() if style["upper"] else text).split("\n")
        path = str(font_path(style["font"]))
        size = style["size"] * height * SS
        limit = style["width"] * width * SS
        for _ in range(2):  # second pass after shrinking to fit the allowed width
            font = ImageFont.truetype(path, max(4, int(round(size))))
            layout = [_advances(font, line, style["tracking"] * size) for line in lines]
            widest = max(w for _, w in layout) or 1.0
            if widest <= limit:
                break
            size *= limit / widest
        ascent, descent = font.getmetrics()
        line_h = size * style["leading"]
        pad = int(size * 0.35)
        block_w, block_h = int(np.ceil(widest)) + 2 * pad, int(np.ceil(line_h * (len(lines) - 1) + ascent + descent)) + 2 * pad
        image = Image.new("L", (block_w, block_h), 0)
        draw = ImageDraw.Draw(image)
        for row, (line, (xs, w)) in enumerate(zip(lines, layout)):
            x0 = pad + {"left": 0.0, "right": widest - w}.get(style["align"], (widest - w) / 2)
            for ch, x in zip(line, xs):
                if not ch.isspace():
                    draw.text((x0 + x, pad + row * line_h), ch, font=font, fill=255)
        box = image.getbbox() or (0, 0, 1, 1)
        image = image.crop(box)
        out_size = (max(1, round(image.width / SS)), max(1, round(image.height / SS)))
        mask = image.resize(out_size, Image.LANCZOS)
        cx, cy = style["pos"][0] * width, style["pos"][1] * height
        left = {"left": cx, "right": cx - out_size[0]}.get(style["align"], cx - out_size[0] / 2)
        self.x, self.y = int(round(left)), int(round(cy - out_size[1] / 2))
        self.mask = np.asarray(mask, np.float32) / 255.0 * float(style["opacity"])
        self.color = np.array(hex_bgr(style["color"]), np.float32)
        self.shadow = None
        if style["shadow"] > 0:
            blur = max(2, int(out_size[1] * 0.12))
            grown = Image.new("L", (out_size[0] + 4 * blur, out_size[1] + 4 * blur), 0)
            grown.paste(mask, (2 * blur, 2 * blur))
            self.shadow = np.asarray(grown.filter(ImageFilter.GaussianBlur(blur)), np.float32) / 255.0 * float(style["shadow"])
            self.shadow_off = (self.x - 2 * blur, self.y - 2 * blur + max(1, blur // 3))
        self.box = (self.x, self.y, self.x + out_size[0], self.y + out_size[1])

    @staticmethod
    def _region(frame, patch, x, y):
        h, w = frame.shape[:2]
        ph, pw = patch.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + pw), min(h, y + ph)
        if x0 >= x1 or y0 >= y1:
            return None, None
        return (slice(y0, y1), slice(x0, x1)), patch[y0 - y:y1 - y, x0 - x:x1 - x]

    def draw(self, frame: np.ndarray, opacity: float) -> None:
        """Composite onto ``frame`` in place."""
        if opacity <= 0:
            return
        if self.shadow is not None:
            where, a = self._region(frame, self.shadow, *self.shadow_off)
            if where:
                frame[where] = (frame[where] * (1.0 - a[..., None] * opacity)).astype(np.uint8)
        where, a = self._region(frame, self.mask, self.x, self.y)
        if where:
            a = a[..., None] * opacity
            frame[where] = (frame[where] * (1.0 - a) + self.color * a + 0.5).astype(np.uint8)


def schedule(titles: list[dict], fps: float) -> list[dict]:
    """Frame ranges and fade lengths for each title."""
    out = []
    for spec in titles or []:
        fade = spec.get("fade", [0.0, 0.0])
        fade = [fade, fade] if isinstance(fade, (int, float)) else list(fade)
        f0 = int(round(spec["at"] * fps))
        out.append({"spec": spec, "f0": f0, "f1": f0 + max(1, int(round(spec["dur"] * fps))),
                    "fade_in": int(round(fade[0] * fps)), "fade_out": int(round(fade[1] * fps))})
    return out


def opacity_at(item: dict, frame: int) -> float:
    if not item["f0"] <= frame < item["f1"]:
        return 0.0
    k_in = (frame - item["f0"] + 1) / (item["fade_in"] + 1) if item["fade_in"] else 1.0
    k_out = (item["f1"] - frame) / (item["fade_out"] + 1) if item["fade_out"] else 1.0
    return float(min(1.0, k_in, k_out))
