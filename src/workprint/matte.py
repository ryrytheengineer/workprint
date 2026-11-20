"""Mattes: separating a subject from what is behind it.

A matte lets words sit *behind* a subject, and lets a still photograph be split into
layers that move at different rates. Finding one needs a trained model; Workprint uses
an optional salient-object model that is downloaded only when asked for
(``workprint matte setup --yes``) and used only if its checksum matches. It finds "the
thing the picture is of": it has no idea which subject you mean, it softens on dark or
busy footage, and it runs at roughly one to two seconds a frame on a laptop CPU, so use
it on chosen moments, not whole films.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from .voice import _importable, home

MODEL = {
    "name": "isnet-general-use",
    "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
    "sha256": "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
    "bytes": 178648008,
    "about": "IS-Net general-use weights from the DIS project (Xuebin Qin et al.), in the ONNX file published by the rembg project",
}
PACKAGES = ("onnxruntime>=1.16",)
SIZE = 1024


class MatteError(RuntimeError):
    pass


def model_path() -> Path:
    return home() / "models" / (MODEL["name"] + ".onnx")


def tools() -> dict:
    return {"runtime": _importable("onnxruntime"), "model": model_path().exists()}


def setup(progress=print) -> dict:
    """Install the runtime and fetch the model. Explicit and checksum-verified."""
    if not _importable("onnxruntime"):
        progress(f"installing {PACKAGES[0]}")
        uv = shutil.which("uv")
        command = ([uv, "pip", "install", "--quiet", "--python", sys.executable] if uv else
                   [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"])
        done = subprocess.run([*command, *PACKAGES], capture_output=True, text=True)
        if done.returncode:
            raise MatteError("pip could not install the matte runtime:\n" + done.stderr.strip()[-600:])
    target = model_path()
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        progress("note: the cut-out model is not cleared for commercial use; see THIRD_PARTY.md")
        progress(f"downloading the matte model ({MODEL['bytes'] / 1e6:.0f} MB) from {MODEL['url']}")
        digest = hashlib.sha256()
        with urllib.request.urlopen(MODEL["url"], timeout=60) as response, open(partial, "wb") as out:
            while block := response.read(1 << 20):
                digest.update(block)
                out.write(block)
        if digest.hexdigest() != MODEL["sha256"]:
            partial.unlink(missing_ok=True)
            raise MatteError("the downloaded model does not match its expected checksum; nothing was installed")
        partial.replace(target)
    return tools()


_session = None


def lifted(image: np.ndarray) -> np.ndarray:
    """The picture stretched to full range with its shadows opened, for the matte model's eyes only:
    a subject graded down to a dusk silhouette is then found as cleanly as it is in daylight."""
    x = image.astype(np.float32)
    lo, hi = np.percentile(x, 1.0), np.percentile(x, 99.5)
    x = np.clip((x - lo) / max(hi - lo, 1.0), 0.0, 1.0) ** 0.6
    return (x * 255.0 + 0.5).astype(np.uint8)


def subject(frame: np.ndarray, lift: bool = False) -> np.ndarray:
    """Alpha (0..1, same height and width as ``frame``) of the picture's subject. ``lift`` reads a dim frame
    brightened first (the alpha still fits the frame as given)."""
    global _session
    have = tools()
    if not all(have.values()):
        raise MatteError("mattes need the matte tools: run `workprint matte setup`")
    if _session is None:
        import os
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
        _session = ort.InferenceSession(str(model_path()), options, providers=["CPUExecutionProvider"])
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    x = (lifted(small) if lift else small)[..., ::-1].astype(np.float32) / 255.0 - 0.5
    y = _session.run(None, {_session.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    y = (y - y.min()) / (y.max() - y.min() + 1e-6)
    return cv2.resize(y, (w, h), interpolation=cv2.INTER_LINEAR)


class Tracker:
    """Mattes for consecutive frames of one shot, steadied against flicker."""

    def __init__(self, steady: float = 0.5):
        self.steady, self.last = steady, None

    def reset(self) -> None:
        self.last = None

    def of(self, frame: np.ndarray, lift: bool = False) -> np.ndarray:
        alpha = subject(frame, lift=True) if lift else subject(frame)
        if self.last is not None and self.last.shape == alpha.shape:
            alpha = self.steady * self.last + (1.0 - self.steady) * alpha
        self.last = alpha
        return alpha


def over(front: np.ndarray, back: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """``front`` where the matte is solid, ``back`` elsewhere."""
    a = alpha[..., None].astype(np.float32)
    return (front * a + back * (1.0 - a) + 0.5).astype(np.uint8)


def solid_alpha(alpha: np.ndarray, low: float = 0.35, span: float = 0.3) -> np.ndarray:
    """A matte made firm for a cut-out that must read as solid: the soft fringe tightened to a few pixels.
    Words set behind a subject use a lower threshold, so a dim, low-contrast subject still hides them fully."""
    return np.clip((alpha.astype(np.float32) - low) / span, 0.0, 1.0)


def revolve(subject: np.ndarray, alpha: np.ndarray, back: np.ndarray, p0: float, p1: float, leaving: bool,
            spin: float = 1.0, steps: int = 6, turn: float = 260.0, rise: float = 0.18, grow: float = 0.35,
            shutter: float = 1.0) -> np.ndarray:
    """A cut-out that spins out of the frame (``leaving``) or spins in and lands in place, over ``back``.

    ``p0``..``p1`` is the stretch of the move this frame covers; it is sampled ``steps`` times and averaged, which gives
    the spin real motion blur. ``spin`` is +1 or -1: which way it turns and which side it flies to or from.
    ``turn`` is how far it rotates (0 flies it off straight), ``rise`` how far it climbs, ``grow`` how much it scales,
    and ``shutter`` how much of the frame's travel is blurred (1 is a full open shutter, 0.4 a crisp streak).
    """
    a = solid_alpha(alpha)
    ys, xs = np.nonzero(a > 0.5)
    if len(xs) == 0:
        return back if leaving else subject
    h, w = back.shape[:2]
    cx, cy = float(xs.mean()), float(ys.mean())
    color = subject.astype(np.float32) * a[..., None]
    acc_c = np.zeros_like(color)
    acc_a = np.zeros(a.shape, np.float32)
    for k in range(steps):
        p = p1 - (p1 - p0) * shutter * (1.0 - (k + 0.5) / steps)
        e = p * p if leaving else (1.0 - p) * (1.0 - p)       # leaving: accelerates away; arriving: decelerates into place
        angle = spin * turn * e
        scale = 1.0 + grow * e
        tx = spin * w * 1.15 * e
        ty = -h * rise * e
        M = cv2.getRotationMatrix2D((cx, cy), angle, scale)
        M[0, 2] += tx
        M[1, 2] += ty
        acc_c += cv2.warpAffine(color, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
        acc_a += cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    acc_c /= steps
    acc_a /= steps
    out = back.astype(np.float32) * (1.0 - acc_a[..., None]) + acc_c
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def wipe(old: np.ndarray, new: np.ndarray, alpha: np.ndarray, p: float, style: str = "through") -> np.ndarray:
    """A transition led by the outgoing shot's subject, at progress ``p`` (0..1).

    ``through``: the new shot opens from the heart of the subject, fills its silhouette, then spreads to the frame.
    ``hold``: the new shot arrives at once behind the subject, which stays a moment and lets go.
    ``pin``: the new shot arrives at once behind the subject, which stays whole, then goes on a hard cut. No fading.
    With no clear subject it falls back to a dissolve (``pin`` falls back to a plain cut).
    """
    solid = alpha > 0.5
    if not solid.any() or solid.all():
        return new if style == "pin" else cv2.addWeighted(old, 1.0 - p, new, p, 0)
    if style == "pin":
        return over(old, new, solid_alpha(alpha))
    if style == "hold":
        return over(old, new, alpha * (1.0 - p * p * (3 - 2 * p)))
    inside = cv2.distanceTransform(solid.astype(np.uint8), cv2.DIST_L2, 3)
    outside = cv2.distanceTransform((~solid).astype(np.uint8), cv2.DIST_L2, 3)
    signed = outside - inside  # negative deep inside the subject, growing outward
    lo, hi = -float(inside.max()) - 1.0, float(outside.max()) + 1.0
    edge = max(2.0, 0.008 * old.shape[1])
    return over(new, old, np.clip((lo + (hi - lo) * p - signed) / edge, 0.0, 1.0))


# ---- stills into shots -----------------------------------------------------------------------------
MOVES = ("push", "drift", "parallax")


def _cover(image: np.ndarray, width: int, height: int, margin: float = 1.25) -> np.ndarray:
    """The image scaled to cover the frame with room to move."""
    k = max(width / image.shape[1], height / image.shape[0]) * margin
    return cv2.resize(image, (int(round(image.shape[1] * k)), int(round(image.shape[0] * k))),
                      interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)


def _view(image: np.ndarray, width: int, height: int, zoom: float, dx: float, dy: float, angle: float = 0.0,
          border=cv2.BORDER_REFLECT) -> np.ndarray:
    """A frame-sized window on ``image``: zoom 1 shows the largest area that fits; dx, dy shift it (fractions of the frame)."""
    ih, iw = image.shape[:2]
    scale = zoom * min(iw / width, ih / height) ** -1  # frame pixels per image pixel
    m = cv2.getRotationMatrix2D((iw / 2 - dx * width / scale, ih / 2 - dy * height / scale), angle, scale)
    m[0, 2] += width / 2 - (iw / 2 - dx * width / scale)
    m[1, 2] += height / 2 - (ih / 2 - dy * height / scale)
    return cv2.warpAffine(image, m, (width, height), flags=cv2.INTER_CUBIC, borderMode=border)


def still_frames(image: np.ndarray, width: int, height: int, count: int, move: str = "drift"):
    """Yield ``count`` frames that turn a photograph into a shot."""
    if move not in MOVES:
        raise MatteError(f"unknown move {move!r} (known: {', '.join(MOVES)})")
    base = _cover(image, width, height)
    ease = lambda p: p * p * (3 - 2 * p)
    if move == "parallax":  # the subject and what is behind it travel at different rates
        alpha = subject(base)
        hole = cv2.dilate((alpha > 0.35).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=max(4, base.shape[1] // 120))
        k = min(1.0, 720.0 / base.shape[1])
        small = cv2.resize(base, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        filled = cv2.inpaint(small, cv2.resize(hole, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST), 7, cv2.INPAINT_TELEA)
        filled = cv2.resize(filled, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_CUBIC)
        soft = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), max(2.0, base.shape[1] / 300))[..., None]
        behind = (filled * soft + base * (1 - soft)).astype(np.uint8)
        layer = np.dstack([base, (alpha * 255).astype(np.uint8)])
    for n in range(count):
        p = ease(n / max(1, count - 1))
        if move == "push":
            yield _view(base, width, height, 1.0 + 0.14 * p, 0.0, 0.0)
        elif move == "drift":
            yield _view(base, width, height, 1.05 + 0.09 * p, -0.03 + 0.06 * p, 0.012 - 0.024 * p, -0.5 + 1.0 * p)
        else:
            back = _view(behind, width, height, 1.03 + 0.04 * p, 0.012 - 0.024 * p, 0.0)
            front = _view(layer, width, height, 1.03 + 0.13 * p, -0.02 + 0.04 * p, 0.006 * p, border=cv2.BORDER_CONSTANT)
            yield over(front[..., :3], back, front[..., 3].astype(np.float32) / 255.0)
