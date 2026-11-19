"""Captions: words on the picture, timed to the voice.

A caption is a *cue* in the cut: text, when it starts, how long it stays, and a style.

    {"id": "k03", "at": 6.21, "dur": 2.4, "text": "in this day of electricity", "style": "split",
     "words": [[0.0, "in"], [0.18, "this"], [0.41, "day"], [0.93, "of"], [1.07, "electricity"]]}

``words`` holds each word's time as an offset from ``at``, so moving a cue keeps it in
sync with itself. Four styles:

  line   a phrase on the lower third; each word appears as it is spoken
  word   one word at a time, heavy capitals
  split  the phrase in two halves, left and right of frame, the middle left clear;
         the second half arrives on its first word
  punch  one word filling the frame, the picture dimmed behind it

Every line is drawn once and words are revealed by uncovering it, so text never shifts
as it builds. ``set`` on a cue overrides any style value for that cue alone.
"""
from __future__ import annotations

import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .look import hex_bgr
from .titles import SS, _advances, font_path

STYLES = {
    "line": {"font": "sans", "weight": 650, "size": 0.05, "pos": [0.5, 0.86], "color": "#f4f1ea", "case": None, "width": 0.8,
             "shadow": 0.55, "fade": [0.06, 0.1], "reveal": "words", "tracking": 0.0, "leading": 1.22, "max_chars": 38},
    "word": {"font": "display", "weight": None, "size": 0.09, "pos": [0.5, 0.8], "color": "#f4f1ea", "case": "upper", "width": 0.84,
             "shadow": 0.5, "fade": [0.0, 0.0], "reveal": "one", "tracking": 0.0, "leading": 1.1, "max_chars": 30},
    "split": {"font": "serif", "weight": None, "size": 0.082, "pos": [0.5, 0.52], "color": "#f3ecdd", "case": "lower", "width": 0.39,
              "shadow": 0.0, "fade": [0.08, 0.12], "reveal": "halves", "tracking": 0.0, "leading": 1.1, "margin": 0.07, "max_chars": 44},
    "punch": {"font": "display", "weight": None, "size": 0.5, "pos": [0.5, 0.5], "color": "#f4f1ea", "case": "upper", "width": 0.8,
              "shadow": 0.0, "fade": [0.0, 0.0], "reveal": "all", "tracking": -0.01, "leading": 1.0, "dim": 0.5, "max_chars": 16},
}
CAPTIONS_REV = 1  # bump when a change here alters pixels: invalidates only chunks that carry captions
BREAK = re.compile(r"[.!?]$")
SOFT = re.compile(r"[,;:—]$")


def style_of(cue: dict) -> dict:
    return {**STYLES[cue.get("style", "line")], **(cue.get("set") or {})}


def reference(width: int, height: int) -> float:
    """The length caption sizes are relative to: frame height, held back on tall frames."""
    return float(height if width >= height else min(height, width * 1.2))


def _shown(text: str, case: str | None) -> str:
    return text.upper() if case == "upper" else text.lower() if case == "lower" else text


def cue_words(cue: dict) -> list[tuple[float, str]]:
    """(offset seconds, word) for each word of a cue."""
    if cue.get("words"):
        return [(float(t), str(w)) for t, w in cue["words"]]
    return [(0.0, w) for w in str(cue.get("text", "")).replace("|", " ").split()]


class Block:
    """One line of text, drawn once. Any run of its words can be shown without the rest moving."""

    def __init__(self, words: list[str], style: dict, size_px: float, limit_px: float, anchor: tuple[float, float],
                 align: str = "center", middle: bool = False):
        text = " ".join(words)
        path = str(font_path(style["font"]))
        size = size_px * SS
        for _ in range(2):  # second pass after shrinking to fit the allowed width
            font = ImageFont.truetype(path, max(4, int(round(size))))
            if style.get("weight"):
                try:  # variable fonts only: set the weight axis, leave the others at their defaults
                    names = [a["name"].decode() if isinstance(a["name"], bytes) else str(a["name"]) for a in font.get_variation_axes()]
                    font.set_variation_by_axes([float(style["weight"]) if n.lower() in ("weight", "wght") else a["default"]
                                                for n, a in zip(names, font.get_variation_axes())])
                except Exception:
                    pass
            xs, total = _advances(font, text, style.get("tracking", 0.0) * size)
            if total <= limit_px * SS or total <= 0:
                break
            size *= limit_px * SS / total
        self.size = size / SS
        ascent, descent = font.getmetrics()
        pad = int(size * 0.3)
        image = Image.new("L", (int(np.ceil(total)) + 2 * pad, ascent + descent + 2 * pad), 0)
        draw = ImageDraw.Draw(image)
        for ch, x in zip(text, xs):
            if not ch.isspace():
                draw.text((pad + x, pad), ch, font=font, fill=255)
        out = (max(1, round(image.width / SS)), max(1, round(image.height / SS)))
        self.mask = np.asarray(image.resize(out, Image.LANCZOS), np.float32) / 255.0
        space = font.getlength(" ")
        self.spans, k = [], 0
        for word in words:  # column range of each word, split in the middle of the spaces
            a = xs[k] - space / 2
            b = (xs[k + len(word)] if k + len(word) < len(xs) else total) - (space / 2 if k + len(word) < len(xs) else -space / 2)
            self.spans.append((max(0, int((pad + a) / SS)), min(out[0], int(np.ceil((pad + b) / SS)))))
            k += len(word) + 1
        ink_w, pad_out = total / SS, pad / SS
        left = anchor[0] - pad_out - {"left": 0.0, "right": ink_w}.get(align, ink_w / 2)
        top = anchor[1] - (pad + ascent) / SS  # anchor is the baseline
        if middle:  # centre the ink itself on the anchor
            rows = np.flatnonzero(self.mask.max(1) > 0.05)
            if len(rows):
                top = anchor[1] - (rows[0] + rows[-1] + 1) / 2
        self.x, self.y = int(round(left)), int(round(top))
        self.color = np.array(hex_bgr(style["color"]), np.float32)
        self.shadow_strength = float(style.get("shadow") or 0.0)
        self._states: dict = {}

    def _state(self, lo: int, hi: int):
        key = (lo, hi)
        if key not in self._states:
            x0, x1 = self.spans[lo][0], self.spans[hi - 1][1]
            mask = self.mask[:, x0:x1]
            shadow, blur = None, 0
            if self.shadow_strength > 0:
                blur = max(2, int(self.size * 0.14))
                grown = cv2.copyMakeBorder(mask, 2 * blur, 2 * blur, 2 * blur, 2 * blur, cv2.BORDER_CONSTANT, value=0)
                shadow = np.clip(cv2.GaussianBlur(grown, (0, 0), blur) * 1.6, 0.0, 1.0) * self.shadow_strength
            self._states[key] = (mask, x0, shadow, blur)
        return self._states[key]

    @staticmethod
    def _region(frame, patch, x, y):
        h, w = frame.shape[:2]
        ph, pw = patch.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + pw), min(h, y + ph)
        if x0 >= x1 or y0 >= y1:
            return None, None
        return (slice(y0, y1), slice(x0, x1)), patch[y0 - y:y1 - y, x0 - x:x1 - x]

    def box(self, lo: int = 0, hi: int | None = None) -> tuple[int, int, int, int]:
        """Frame rectangle of the ink of words lo..hi-1."""
        hi = len(self.spans) if hi is None else hi
        x0, x1 = self.spans[lo][0], self.spans[hi - 1][1]
        part = self.mask[:, x0:x1] > 0.05
        rows, cols = np.flatnonzero(part.any(1)), np.flatnonzero(part.any(0))
        if not len(rows):
            return self.x + x0, self.y, self.x + x1, self.y + self.mask.shape[0]
        return self.x + x0 + int(cols[0]), self.y + int(rows[0]), self.x + x0 + int(cols[-1]) + 1, self.y + int(rows[-1]) + 1

    def draw(self, frame: np.ndarray, opacity: float, lo: int = 0, hi: int | None = None) -> None:
        """Composite words lo..hi-1 onto ``frame`` in place."""
        hi = len(self.spans) if hi is None else hi
        if opacity <= 0 or hi <= lo:
            return
        mask, x0, shadow, blur = self._state(lo, hi)
        if shadow is not None:
            where, a = self._region(frame, shadow, self.x + x0 - 2 * blur, self.y - 2 * blur + max(1, blur // 3))
            if where:
                frame[where] = (frame[where] * (1.0 - a[..., None] * opacity)).astype(np.uint8)
        where, a = self._region(frame, mask, self.x + x0, self.y)
        if where:
            a = a[..., None] * opacity
            frame[where] = (frame[where] * (1.0 - a) + self.color * a + 0.5).astype(np.uint8)


def _halves(words: list[str], text: str) -> int:
    """Index of the first word of the second half."""
    if "|" in text:
        return max(1, min(len(words) - 1, len(text.split("|")[0].split())))
    if len(words) < 2:
        return len(words)
    total = sum(len(w) + 1 for w in words)
    best, at, run = None, 1, 0
    for k in range(1, len(words)):
        run += len(words[k - 1]) + 1
        score = abs(run - total / 2) - (2.5 if SOFT.search(words[k - 1]) or BREAK.search(words[k - 1]) else 0.0)
        if best is None or score < best:
            best, at = score, k
    return at


def _wrap(words: list[str], style: dict, size_px: float, limit_px: float) -> list[tuple[int, int]]:
    """Word index ranges for one or two balanced lines."""
    font = ImageFont.truetype(str(font_path(style["font"])), max(4, int(round(size_px))))
    if len(words) < 2 or font.getlength(" ".join(words)) <= limit_px:
        return [(0, len(words))]
    k = min(range(1, len(words)), key=lambda i: max(font.getlength(" ".join(words[:i])), font.getlength(" ".join(words[i:]))))
    return [(0, k), (k, len(words))]


def compile_cue(cue: dict, fps: float, width: int, height: int) -> list[dict]:
    """Turn a cue into pieces the renderer can draw: {block, f0, f1, lo, hi, fade_in, fade_out, dim}."""
    style = style_of(cue)
    timed = cue_words(cue)
    if not timed:
        return []
    words = [_shown(w, style["case"]) for _, w in timed]
    if style.get("reveal") == "one" or cue.get("style") == "punch":  # a word standing alone drops its comma or full stop
        words = [re.sub(r"[.,;:]+$", "", w) or w for w in words]
    f0 = int(round(cue["at"] * fps))
    f1 = f0 + max(1, int(round(cue["dur"] * fps)))
    on = [min(f1 - 1, max(f0, int(round((cue["at"] + t) * fps)))) for t, _ in timed]
    if not cue.get("words") and style.get("reveal") == "one":  # untimed: share the time evenly
        on = [f0 + k * (f1 - f0) // len(timed) for k in range(len(timed))]
    fade = style.get("fade") or [0.0, 0.0]
    fade_in, fade_out = int(round(fade[0] * fps)), int(round(fade[1] * fps))
    ref = reference(width, height)
    size, limit = style["size"] * ref, style["width"] * width
    cx, cy = style["pos"][0] * width, style["pos"][1] * height
    reveal = style.get("reveal", "all")
    pieces: list[dict] = []

    def piece(block, a, b, lo, hi, first=True, last=True, dim=0.0):
        if b > a:
            pieces.append({"block": block, "f0": a, "f1": b, "lo": lo, "hi": hi, "fade_in": fade_in if first else 0,
                           "fade_out": fade_out if last else 0, "dim": dim})

    if reveal == "one":
        for k, word in enumerate(words):
            block = Block([word], style, size, limit, (cx, cy))
            piece(block, on[k], on[k + 1] if k + 1 < len(words) else f1, 0, 1)
    elif reveal == "halves":
        cut_at = _halves(words, str(cue.get("text", "")))
        margin = style.get("margin", 0.07) * width
        drop = 0.0
        if width < height:  # a tall frame has no room side by side: first half up and left, second down and right
            limit, drop = width - 2.4 * margin, 0.62 * size
        left = Block(words[:cut_at], style, size, limit, (margin, cy - drop), "left")
        if cut_at < len(words):
            right = Block(words[cut_at:], style, min(size, left.size), limit, (width - margin, cy + drop), "right")
            if right.size < left.size - 0.5:  # keep both halves the same size
                left = Block(words[:cut_at], style, right.size, limit, (margin, cy - drop), "left")
            piece(right, on[cut_at], f1, 0, len(words) - cut_at)
        piece(left, f0, f1, 0, cut_at)
    elif cue.get("style") == "punch" or style.get("dim"):
        block = Block(words, style, min(size, 0.6 * height), limit, (cx, cy), middle=True)
        piece(block, f0, f1, 0, len(words), dim=float(style.get("dim") or 0.0))
    else:
        lines = _wrap(words, style, size, limit)
        for row, (a, b) in enumerate(lines):
            y = cy - (len(lines) - 1 - row) * style.get("leading", 1.2) * size
            block = Block(words[a:b], style, size, limit, (cx, y))
            if reveal == "words":
                for k in range(a, b):
                    start = f0 if k == 0 else on[k]
                    piece(block, start, on[k + 1] if k + 1 < len(words) else f1, 0, k - a + 1, first=(k == a), last=False)
                if b < len(words):  # the finished line stays while the next one builds
                    piece(block, on[b], f1, 0, b - a, first=False)
                elif pieces:
                    pieces[-1]["fade_out"] = fade_out
            else:
                piece(block, f0, f1, 0, b - a)
    return pieces


def opacity(piece: dict, frame: int) -> float:
    if not piece["f0"] <= frame < piece["f1"]:
        return 0.0
    k_in = (frame - piece["f0"] + 1) / (piece["fade_in"] + 1) if piece["fade_in"] else 1.0
    k_out = (piece["f1"] - frame) / (piece["fade_out"] + 1) if piece["fade_out"] else 1.0
    return float(min(1.0, k_in, k_out))


def draw(pieces: list[dict], frame: np.ndarray, index: int) -> np.ndarray:
    """Draw every piece active at frame ``index``. Returns the frame (copied if it had to be)."""
    active = [(p, opacity(p, index)) for p in pieces if p["f0"] <= index < p["f1"]]
    if not active:
        return frame
    if not frame.flags.writeable:
        frame = frame.copy()
    dim = max((p["dim"] * a for p, a in active), default=0.0)
    if dim > 0:
        np.multiply(frame, 1.0 - dim, out=frame, casting="unsafe")
    for p, a in active:
        p["block"].draw(frame, a, p["lo"], p["hi"])
    return frame


def key_part(cues: list[dict], f0: int, f1: int, fps: float) -> list:
    """What a chunk's cache key needs to know about the captions over it."""
    out = []
    for cue in cues or []:
        a = int(round(cue["at"] * fps))
        if a < f1 and a + max(1, int(round(cue["dur"] * fps))) > f0:
            out.append([{k: v for k, v in cue.items() if k not in ("id", "at", "note", "voice")}, a - f0])
    return [CAPTIONS_REV, out] if out else []


# ---- making cues from a voice --------------------------------------------------------------------
def from_words(words: list[dict], style: str = "line", punch=(), pause: float = 0.3, lead: float = 0.04,
               linger: float = 0.4, voice: str | None = None, fps: float = 24.0) -> list[dict]:
    """Group timed words (timeline seconds) into cues. Words named in ``punch`` become full-frame cues of their own."""
    from .voice import plain
    limit = STYLES[style]["max_chars"]
    wanted = {(plain(p.split(":")[0]), int(p.split(":")[1]) if ":" in p else 0) for p in map(str, punch)}
    said: dict[str, int] = {}
    groups: list[tuple[str, list[dict]]] = []
    current: list[dict] = []

    def flush():
        if current:
            groups.append((style, list(current)))
            current.clear()

    for word in words:
        key = plain(word["w"])
        said[key] = said.get(key, 0) + 1
        if (key, 0) in wanted or (key, said[key]) in wanted:
            flush()
            groups.append(("punch", [word]))
            continue
        if current:
            prev = current[-1]
            chars = sum(len(w["w"]) + 1 for w in current)
            if (word["s"] - prev["e"] >= pause or BREAK.search(prev["w"]) or chars + len(word["w"]) > limit
                    or (SOFT.search(prev["w"]) and chars >= limit * 0.5)):
                flush()
        current.append(word)
    flush()
    cues = []
    for kind, group in groups:
        at = max(0.0, group[0]["s"] - (0.0 if kind == "punch" else lead))
        end = group[-1]["e"] + (0.3 if kind == "punch" else linger)
        text = " ".join(w["w"] for w in group)
        cue = {"at": round(at, 3), "dur": round(end - at, 3), "text": re.sub(r"[.,;:!?]+$", "", text) if kind == "punch" else text,
               "style": kind, "words": [[round(max(0.0, w["s"] - at), 3), w["w"]] for w in group]}
        if kind == "punch":
            cue["words"] = [[0.0, cue["text"]]]
        if voice:
            cue["voice"] = voice
        cues.append(cue)
    for cue, nxt in zip(cues, cues[1:]):  # one caption at a time
        if cue["at"] + cue["dur"] > nxt["at"] - 0.5 / fps:
            cue["dur"] = round(max(1.0 / fps, nxt["at"] - 0.5 / fps - cue["at"]), 3)
    return cues


def problems(cut: dict) -> tuple[list[str], list[str]]:
    """Errors and warnings about the captions in a cut."""
    errors, warnings = [], []
    fps, total = cut["format"]["fps"], cut.get("duration", 0.0)
    cues = sorted(cut.get("captions") or [], key=lambda c: c.get("at", 0.0))
    for cue in cues:
        name = cue.get("id", "caption")
        if cue.get("style", "line") not in STYLES:
            errors.append(f"{name}: unknown caption style {cue.get('style')!r} (known: {', '.join(STYLES)})")
            continue
        if not str(cue.get("text", "")).strip() or "at" not in cue or cue.get("dur", 0) <= 0:
            errors.append(f"{name}: a caption needs text, at and a positive dur")
            continue
        style, text = style_of(cue), str(cue["text"])
        if cue["at"] < 0 or cue["at"] + cue["dur"] > total + 1.0 / fps:
            warnings.append(f"{name}: caption runs outside the film")
        if cue["dur"] < 0.3:
            warnings.append(f"{name}: on screen for {cue['dur']:.2f}s, too short to read")
        elif style.get("reveal") != "one" and cue.get("style") != "punch" and len(text) / cue["dur"] > 24:
            warnings.append(f"{name}: {len(text) / cue['dur']:.0f} characters a second is fast to read ({text[:28]!r})")
        if cue.get("style") == "punch" and len(text.split()) > 3:
            warnings.append(f"{name}: a punch caption works with one to three words, this has {len(text.split())}")
        if cue.get("words") and len(cue["words"]) != len(text.replace("|", " ").split()):
            warnings.append(f"{name}: text and word timings disagree; the timings are drawn. Clear them with `set {name} words=`")
    for a, b in zip(cues, cues[1:]):
        if "at" in a and "at" in b and a["at"] + a.get("dur", 0) > b["at"] + 0.5 / fps and a.get("style") != "punch" != b.get("style"):
            warnings.append(f"{a.get('id')} and {b.get('id')} are on screen together")
    return errors, warnings
