"""Picture treatment: grade, look, and the small set of frame effects.

Everything here is deterministic: the same parameters always give the same pixels,
which is what lets rendered chunks be cached and reused across revisions.
The pipeline is 8-bit; grain is added last and doubles as dither.
"""
from __future__ import annotations

import cv2
import numpy as np

# Starting points, not styles to lean on. Every value can be overridden per project.
PRESETS: dict[str, dict] = {
    "none": {},
    "steel": {"contrast": 1.10, "saturation": 0.84, "temperature": -0.10, "lift": [0.0, 0.004, 0.012], "gamma": 0.97},
    "print": {"contrast": 1.05, "saturation": 0.93, "temperature": 0.07, "fade": 0.025, "gain": [1.02, 1.0, 0.96]},
    "bleach": {"contrast": 1.22, "saturation": 0.55},
    "noir": {"contrast": 1.15, "saturation": 0.0},
}
GRADE_KEYS = ("exposure", "contrast", "saturation", "temperature", "tint", "lift", "gamma", "gain", "fade")


def hex_bgr(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def resolve_look(look: dict | None) -> dict:
    """Merge a preset with explicit grade overrides into one flat description."""
    look = dict(look or {})
    grade = dict(PRESETS.get(look.get("preset", "none"), {}))
    grade.update(look.get("grade") or {})
    return {"grade": grade, "grain": float(look.get("grain", 0.0)), "vignette": float(look.get("vignette", 0.0)),
            "letterbox": float(look.get("letterbox", 0.0))}


def _triple(value, default: float) -> np.ndarray:
    if value is None:
        return np.full(3, default)
    return np.array(value, float) if isinstance(value, (list, tuple)) else np.full(3, float(value))


class Grade:
    """A grade compiled to per-channel lookup tables plus a saturation matrix."""

    def __init__(self, params: dict | None):
        params = params or {}
        self.neutral = not any(k in params for k in GRADE_KEYS)
        self.lut = None
        self.matrix = None
        if self.neutral:
            return
        x = np.linspace(0.0, 1.0, 256)
        temp, tint = float(params.get("temperature", 0.0)), float(params.get("tint", 0.0))
        white = np.array([1 + 0.25 * temp, 1 - 0.2 * tint, 1 - 0.25 * temp])  # R, G, B
        exposure = 2.0 ** float(params.get("exposure", 0.0))
        gain, lift, gamma = _triple(params.get("gain"), 1.0), _triple(params.get("lift"), 0.0), _triple(params.get("gamma"), 1.0)
        contrast, fade, pivot = float(params.get("contrast", 1.0)), float(params.get("fade", 0.0)), 0.45
        channels = []
        for c in range(3):
            v = np.clip((x ** 2.2) * exposure * white[c], 0.0, None) ** (1 / 2.2)  # exposure and balance in linear light
            v = v * gain[c]
            v = v + lift[c] * (1.0 - v)
            v = np.clip(v, 0.0, None) ** (1.0 / max(gamma[c], 1e-3))
            v = (v - pivot) * contrast + pivot
            v = fade + v * (1.0 - fade)
            channels.append(np.clip(v, 0.0, 1.0))
        rgb = np.stack(channels, 1)
        self.lut = np.round(rgb[:, ::-1] * 255).astype(np.uint8).reshape(256, 1, 3)  # BGR order
        sat = float(params.get("saturation", 1.0))
        if abs(sat - 1.0) > 1e-6:
            w = np.array([0.0722, 0.7152, 0.2126])  # luma weights in BGR order
            self.matrix = (np.eye(3) * sat + (1 - sat) * np.tile(w, (3, 1))).astype(np.float32)

    def apply(self, frame: np.ndarray) -> np.ndarray:
        if self.neutral:
            return frame
        out = cv2.LUT(frame, self.lut)
        if self.matrix is not None:
            out = cv2.transform(out, self.matrix)
        return out


class Finish:
    """The film-wide look applied after everything else: grade, vignette, grain, letterbox."""

    def __init__(self, look: dict, width: int, height: int):
        spec = resolve_look(look)
        self.grade = Grade(spec["grade"])
        self.vignette = None
        if spec["vignette"] > 0:
            yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
            r = np.hypot((xx - width / 2) / (width / 2), (yy - height / 2) / (height / 2)) / np.sqrt(2)
            t = np.clip((r - 0.45) / 0.55, 0, 1)
            falloff = 1.0 - spec["vignette"] * (t * t * (3 - 2 * t))
            self.vignette = cv2.merge([np.round(falloff * 255).astype(np.uint8)] * 3)
        self.grain = None
        if spec["grain"] > 0:
            rng = np.random.default_rng(1977)
            sigma = spec["grain"] * 255.0
            tiles = []
            for _ in range(8):
                noise = cv2.GaussianBlur(rng.normal(0.0, sigma, (height, width)).astype(np.float32), (0, 0), 0.6)
                tiles.append(cv2.merge([np.clip(np.round(noise * 1.6 + 128), 0, 255).astype(np.uint8)] * 3))
            self.grain = tiles
        self.bar = 0
        if spec["letterbox"] > 0:
            self.bar = max(0, int(round((height - width / spec["letterbox"]) / 2)))

    def apply(self, frame: np.ndarray, index: int) -> np.ndarray:
        frame = self.grade.apply(frame)
        if self.vignette is not None:
            frame = cv2.multiply(frame, self.vignette, scale=1 / 255.0)
        if self.grain is not None:
            frame = cv2.addWeighted(frame, 1.0, self.grain[index % len(self.grain)], 1.0, -128.0)
        if self.bar:
            if not frame.flags.writeable:
                frame = frame.copy()
            frame[: self.bar] = 0
            frame[-self.bar:] = 0
        return frame


# ---- frame effects ------------------------------------------------------------------------------

def _zoom_about_centre(frame: np.ndarray, z: float) -> np.ndarray:
    h, w = frame.shape[:2]
    m = np.float32([[z, 0, (1 - z) * w / 2], [0, z, (1 - z) * h / 2]])
    return cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def xray(frame: np.ndarray, spec: dict | None = None) -> np.ndarray:
    """The x-ray look. Options: ``tint`` (hex colour of the highlights), ``detail`` (edge strength), ``deep``
    (local contrast and a soft glow, for flat or dark footage), ``positive`` (do not invert: for footage that is mostly dark)."""
    spec = spec or {}
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if spec.get("deep"):
        gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.convertScaleAbs(cv2.Laplacian(gray, cv2.CV_16S, ksize=3), alpha=float(spec.get("detail", 1.5)))
    inv = cv2.add(gray if spec.get("positive") else 255 - gray, edges)  # positive: keep dark footage dark, light the edges
    if spec.get("deep"):
        inv = cv2.addWeighted(inv, 0.85, cv2.GaussianBlur(inv, (0, 0), max(2.0, frame.shape[0] * 0.012)), 0.35, 0)
    b, g, r = (c / 255.0 for c in hex_bgr(spec["tint"])) if spec.get("tint") else (1.0, 0.92, 0.78)
    top = max(b, g, r, 1e-6)
    channels = [inv if abs(c / top - 1.0) < 1e-6 else cv2.convertScaleAbs(inv, alpha=c / top) for c in (b, g, r)]
    return cv2.merge(channels)


def apply_fx(frame: np.ndarray, fx_list: list, local: int, frames: int) -> np.ndarray:
    """Apply a slot's effects to one frame. ``local`` is the frame index inside the slot."""
    for fx in fx_list or []:
        spec = {"name": fx} if isinstance(fx, str) else dict(fx)
        name = spec["name"]
        start = int(spec.get("from", 0))
        end = int(spec.get("to", start + int(spec.get("frames", 4)) if name == "punch" else frames))
        if not start <= local < end:
            continue
        k = local - start
        if name == "punch":  # a short zoom kick that settles: lands a hit on the cut
            span = max(1, end - start)
            frame = _zoom_about_centre(frame, 1.0 + float(spec.get("amount", 0.10)) * (1 - k / span) ** 2)
        elif name == "rgbsplit":
            px = int(spec.get("px", 6))
            out = frame.copy()
            out[:, px:, 2] = frame[:, :-px, 2]
            out[:, :-px, 0] = frame[:, px:, 0]
            frame = out
        elif name == "invert":
            frame = 255 - frame
        elif name == "mono":
            frame = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        elif name == "xray":  # inverted luminance, cold tint, edges lifted
            frame = xray(frame, spec)
        elif name == "xray-pulse":  # hits as x-ray and settles back to the picture (shape: out), or the reverse (in)
            p = k / max(1, end - start - 1)
            amount = {"in": ease(p, "in"), "inout": 1.0 - abs(2.0 * p - 1.0)}.get(spec.get("shape", "out"), 1.0 - ease(p, "out"))
            frame = cv2.addWeighted(xray(frame, spec), amount, frame, 1.0 - amount, 0)
        elif name == "xray-flicker":  # x-ray and picture alternate in short runs
            from .manifest import alternate_frames
            if k not in alternate_frames(end - start, 0, None, int(spec.get("every", 2)), spec.get("pattern")):
                frame = xray(frame, spec)
        elif name == "xray-scan":  # a scan line crosses the frame; what it has passed (or a band behind it) is x-ray
            h, w = frame.shape[:2]
            direction = spec.get("dir", "right")
            length = w if direction in ("right", "left") else h
            band = float(spec.get("width", 0.0))  # 0 = everything behind the line stays x-ray
            p = ease(k / max(1, end - start - 1), spec.get("ease", "linear")) * (1.0 + band)
            lead = int(round(p * length))
            tail = 0 if band <= 0 else max(0, lead - int(round(band * length)))
            lead_c = min(length, lead)
            if direction in ("left", "up"):
                tail, lead_c, edge = length - lead_c, length - tail, length - lead
            else:
                edge = lead
            out, seen = frame.copy(), xray(frame, spec)
            line = max(2, int(round(length * 0.004)))
            if direction in ("right", "left"):
                out[:, tail:lead_c] = seen[:, tail:lead_c]
                if 0 <= edge < length:
                    out[:, max(0, edge - line):edge + line] = 255
            else:
                out[tail:lead_c] = seen[tail:lead_c]
                if 0 <= edge < length:
                    out[max(0, edge - line):edge + line] = 255
            frame = out
        elif name == "shake":
            rng = np.random.default_rng(int(spec.get("seed", 7)) * 100003 + local)
            dx, dy = rng.uniform(-1, 1, 2) * float(spec.get("px", 8))
            h, w = frame.shape[:2]
            frame = cv2.warpAffine(frame, np.float32([[1.02, 0, dx - 0.01 * w], [0, 1.02, dy - 0.01 * h]]), (w, h),
                                   flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return frame


def ease(p: float, kind: str = "linear") -> float:
    p = min(max(p, 0.0), 1.0)
    if kind == "in":
        return p * p
    if kind == "out":
        return 1 - (1 - p) ** 2
    if kind == "inout":
        return p * p * (3 - 2 * p)
    return p
