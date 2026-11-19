"""HUD: instrument-style overlays drawn over the picture.

Three kinds, each an entry in the cut's ``hud`` list:

  track    brackets (or a box, or a reticle) that follow something through a shot, with an
           optional label and a live position readout. You give the box on the element's
           first frame; a small template tracker follows it from there.
  counter  a number that runs from one value to another, in fixed-width figures.
  rail     thin rules with tick marks along the top and bottom of the frame, corner marks,
           an optional label and a running timecode.

    {"id": "h001", "kind": "track", "at": 12.0, "dur": 2.5, "box": [0.42, 0.2, 0.16, 0.6], "label": "SLS"}
    {"id": "h002", "kind": "counter", "at": 3.0, "dur": 5.0, "from": 0, "to": 3900, "suffix": " HRS", "pos": [0.08, 0.9]}
    {"id": "h003", "kind": "rail", "at": 0.0, "dur": 41.0, "label": "ARSENAL-1", "timecode": true}

The tracker follows texture, not meaning: it holds on a clear, steady subject and drifts
on fast, blurred or turning ones. Keep a track inside one shot.
"""
from __future__ import annotations

import cv2
import numpy as np

from .look import ease, hex_bgr
from .titles import Title

HUD_REV = 1
KINDS = ("track", "counter", "rail")
STYLES = ("corners", "box", "reticle")
DEFAULT = {"color": "#7dffb0", "opacity": 0.9, "size": 0.022, "weight": 0.0022, "style": "corners"}


class Follower:
    """Follows a patch of picture from frame to frame by matching its texture nearby."""

    def __init__(self, frame: np.ndarray, box: tuple[float, float, float, float]):
        x, y, w, h = box
        self.k = min(1.0, 80.0 / max(w, h, 1.0))
        self.w, self.h = max(4, int(round(w * self.k))), max(4, int(round(h * self.k)))
        self.x, self.y = x * self.k, y * self.k
        small = self._small(frame)
        self.template = self._patch(small)
        self.score = 1.0

    def _small(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.k < 1.0:
            gray = cv2.resize(gray, None, fx=self.k, fy=self.k, interpolation=cv2.INTER_AREA)
        return gray.astype(np.float32)

    def _patch(self, small: np.ndarray) -> np.ndarray:
        x = int(round(min(max(self.x, 0), small.shape[1] - self.w)))
        y = int(round(min(max(self.y, 0), small.shape[0] - self.h)))
        return small[y:y + self.h, x:x + self.w].copy()

    def step(self, frame: np.ndarray) -> tuple[float, float, float, float]:
        small = self._small(frame)
        reach = int(max(10, 0.5 * max(self.w, self.h)))
        x0, y0 = int(max(0, round(self.x) - reach)), int(max(0, round(self.y) - reach))
        x1, y1 = int(min(small.shape[1], round(self.x) + self.w + reach)), int(min(small.shape[0], round(self.y) + self.h + reach))
        region = small[y0:y1, x0:x1]
        if region.shape[0] >= self.h and region.shape[1] >= self.w and self.template.shape == (self.h, self.w):
            scores = cv2.matchTemplate(region, self.template, cv2.TM_CCOEFF_NORMED)
            _, self.score, _, where = cv2.minMaxLoc(scores)
            if self.score >= 0.35:  # confident enough to move; otherwise hold
                self.x += 0.85 * (x0 + where[0] - self.x)
                self.y += 0.85 * (y0 + where[1] - self.y)
                if self.score >= 0.6:  # and to learn the subject's changing look, slowly
                    self.template = 0.92 * self.template + 0.08 * self._patch(small)
        return self.box()

    def box(self) -> tuple[float, float, float, float]:
        return self.x / self.k, self.y / self.k, self.w / self.k, self.h / self.k


class Hud:
    """All HUD elements of a cut at one frame size."""

    def __init__(self, items: list[dict] | None, fps: float, width: int, height: int):
        self.fps, self.W, self.H = fps, width, height
        self.items = []
        for spec in items or []:
            f0 = int(round(spec["at"] * fps))
            self.items.append({"spec": {**DEFAULT, **spec}, "f0": f0, "f1": f0 + max(1, int(round(spec["dur"] * fps))), "follow": None})
        self._text: dict = {}

    def active(self, frame: int) -> bool:
        return any(i["f0"] <= frame < i["f1"] for i in self.items)

    def key_part(self, f0: int, f1: int) -> list:
        out = [[{k: v for k, v in i["spec"].items() if k not in ("id", "at", "note")}, i["f0"] - f0] for i in self.items if i["f0"] < f1 and i["f1"] > f0]
        return [HUD_REV, out] if out else []

    def _label(self, text: str, spec: dict, scale: float = 1.0) -> Title:
        key = (text, spec["color"], spec["size"], scale)
        if key not in self._text:
            self._text[key] = Title({"text": text, "style": {"font": "sans", "size": spec["size"] * scale, "upper": True, "tracking": 0.08,
                                                               "color": spec["color"], "pos": [0, 0], "align": "left", "width": 2.0}}, self.W, self.H)
        return self._text[key]

    def _write(self, frame: np.ndarray, text: str, x: float, y: float, spec: dict, opacity: float, fixed: bool = False, scale: float = 1.0) -> None:
        """Text with its top-left at (x, y). ``fixed`` gives every figure the same width so a running number does not shake."""
        if not fixed:
            label = self._label(text, spec, scale)
            label.x, label.y = int(round(x)), int(round(y))
            label.draw(frame, opacity)
            return
        cell = max(self._label(d, spec, scale).mask.shape[1] for d in "0123456789")
        tall = self._label("0", spec, scale).mask.shape[0]
        gap = max(1, int(cell * 0.16))
        for ch in text:
            if ch == " ":
                x += cell * 0.6
                continue
            glyph = self._label(ch, spec, scale)
            wide = cell if ch.isdigit() else glyph.mask.shape[1]
            glyph.x = int(round(x + (wide - glyph.mask.shape[1]) / 2))
            glyph.y = int(round(y + (tall - glyph.mask.shape[0]) if ch in ",." else y))
            glyph.draw(frame, opacity)
            x += wide + gap

    def draw(self, frame: np.ndarray, index: int) -> np.ndarray:
        """Draw every element active at frame ``index``. Call once per frame, in order, with the clean picture."""
        live = [i for i in self.items if i["f0"] <= index < i["f1"]]
        if not live:
            return frame
        if not frame.flags.writeable:
            frame = frame.copy()
        clean = frame.copy() if any(i["spec"]["kind"] == "track" for i in live) else None
        for item in live:
            spec = item["spec"]
            color, opacity = hex_bgr(spec["color"]), float(spec["opacity"])
            thick = max(1, int(round(spec["weight"] * self.H)))
            layer = frame.copy()
            if spec["kind"] == "track":
                if item["follow"] is None:
                    bx, by, bw, bh = spec["box"]
                    item["follow"] = Follower(clean, (bx * self.W, by * self.H, bw * self.W, bh * self.H))
                    x, y, w, h = item["follow"].box()
                else:
                    x, y, w, h = item["follow"].step(clean)
                x0, y0, x1, y1 = int(round(x)), int(round(y)), int(round(x + w)), int(round(y + h))
                arm = int(max(6, 0.22 * min(w, h)))
                if spec["style"] == "box":
                    cv2.rectangle(layer, (x0, y0), (x1, y1), color, thick, cv2.LINE_AA)
                else:
                    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
                        cv2.line(layer, (cx, cy), (cx + sx * arm, cy), color, thick, cv2.LINE_AA)
                        cv2.line(layer, (cx, cy), (cx, cy + sy * arm), color, thick, cv2.LINE_AA)
                if spec["style"] == "reticle":
                    mx, my, r = (x0 + x1) // 2, (y0 + y1) // 2, max(4, arm // 3)
                    cv2.line(layer, (mx - r, my), (mx + r, my), color, thick, cv2.LINE_AA)
                    cv2.line(layer, (mx, my - r), (mx, my + r), color, thick, cv2.LINE_AA)
                frame = cv2.addWeighted(layer, opacity, frame, 1.0 - opacity, 0)
                tall = self._label("0", spec).mask.shape[0]
                if spec.get("label"):  # above the box, or just inside its top edge when there is no room above
                    above = y0 - tall * 1.9
                    self._write(frame, str(spec["label"]), x0 + (0 if above >= 2 else arm * 0.4), above if above >= 2 else y0 + tall * 0.9, spec, opacity)
                if spec.get("readout"):
                    below = y1 + tall * 0.9
                    self._write(frame, f"X {int(x + w / 2):04d}  Y {int(y + h / 2):04d}", x0 + (0 if below + tall < self.H else arm * 0.4),
                                below if below + tall < self.H else y1 - tall * 1.9, spec, opacity, fixed=True, scale=0.8)
            elif spec["kind"] == "counter":
                p = (index - item["f0"]) / max(1, item["f1"] - item["f0"] - 1)
                value = float(spec["from"]) + (float(spec["to"]) - float(spec["from"])) * ease(p, spec.get("ease", "linear"))
                digits = int(spec.get("decimals", 0))
                text = f"{spec.get('prefix', '')}{value:,.{digits}f}{spec.get('suffix', '')}"
                px, py = spec.get("pos", [0.08, 0.9])
                self._write(frame, text, px * self.W, py * self.H, spec, opacity, fixed=True, scale=float(spec.get("scale", 1.6)))
            else:  # rail
                m = int(round(float(spec.get("margin", 0.055)) * self.H))
                for y, sign in ((m, 1), (self.H - m, -1)):
                    cv2.line(layer, (m, y), (self.W - m, y), color, thick, cv2.LINE_AA)
                    for k in range(0, 41):
                        x = m + int(round(k * (self.W - 2 * m) / 40))
                        cv2.line(layer, (x, y), (x, y + sign * (m // 3 if k % 5 == 0 else m // 7)), color, thick, cv2.LINE_AA)
                frame = cv2.addWeighted(layer, opacity * 0.8, frame, 1.0 - opacity * 0.8, 0)
                tall = self._label("0", spec).mask.shape[0]
                if spec.get("label"):
                    self._write(frame, str(spec["label"]), m, m + m // 2, spec, opacity)
                if spec.get("timecode"):
                    f = int(round(self.fps))
                    stamp = f"{index // (f * 60) % 60:02d}:{index // f % 60:02d}:{index % f:02d}"
                    self._write(frame, stamp, m, self.H - m - m // 2 - tall, spec, opacity, fixed=True)
        return frame


def problems(cut: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    fps = cut["format"]["fps"]
    starts = sorted(c["at"] for c in cut.get("cuts", []))
    for item in cut.get("hud") or []:
        name = item.get("id", "hud")
        if item.get("kind") not in KINDS:
            errors.append(f"{name}: unknown hud kind {item.get('kind')!r} (known: {', '.join(KINDS)})")
            continue
        if "at" not in item or item.get("dur", 0) <= 0:
            errors.append(f"{name}: a hud element needs at and a positive dur")
            continue
        if item["kind"] == "track":
            box = item.get("box")
            if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)
                    and 0 <= box[0] < 1 and 0 <= box[1] < 1 and 0 < box[2] <= 1 and 0 < box[3] <= 1):
                errors.append(f"{name}: track needs box=[x, y, width, height] as fractions of the frame")
            if item.get("style", "corners") not in STYLES:
                errors.append(f"{name}: unknown track style {item.get('style')!r} (known: {', '.join(STYLES)})")
            if any(item["at"] + 0.5 / fps < t < item["at"] + item["dur"] - 0.5 / fps for t in starts):
                warnings.append(f"{name}: the track runs across a cut; it will not find the subject again in the next shot")
        if item["kind"] == "counter" and not ("from" in item and "to" in item):
            errors.append(f"{name}: counter needs from and to")
    return errors, warnings
