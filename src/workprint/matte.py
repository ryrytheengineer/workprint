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


def subject(frame: np.ndarray) -> np.ndarray:
    """Alpha (0..1, same height and width as ``frame``) of the picture's subject."""
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
    x = cv2.resize(frame, (SIZE, SIZE), interpolation=cv2.INTER_AREA)[..., ::-1].astype(np.float32) / 255.0 - 0.5
    y = _session.run(None, {_session.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    y = (y - y.min()) / (y.max() - y.min() + 1e-6)
    return cv2.resize(y, (w, h), interpolation=cv2.INTER_LINEAR)


class Tracker:
    """Mattes for consecutive frames of one shot, steadied against flicker."""

    def __init__(self, steady: float = 0.5):
        self.steady, self.last = steady, None

    def reset(self) -> None:
        self.last = None

    def of(self, frame: np.ndarray) -> np.ndarray:
        alpha = subject(frame)
        if self.last is not None and self.last.shape == alpha.shape:
            alpha = self.steady * self.last + (1.0 - self.steady) * alpha
        self.last = alpha
        return alpha


def over(front: np.ndarray, back: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """``front`` where the matte is solid, ``back`` elsewhere."""
    a = alpha[..., None].astype(np.float32)
    return (front * a + back * (1.0 - a) + 0.5).astype(np.uint8)


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
