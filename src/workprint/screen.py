"""Footage playing on a screen in a still image.

Give it a photograph or render with a television, monitor, phone or billboard in it, the four
corners of that screen, and a clip. It returns frames of the still with the clip playing on
the screen: bent to the screen's shape, given the look of a tube or a flat panel, throwing
its light onto whatever surrounds it, while a camera pushes in.

The screen is described by its four corners (top-left, top-right, bottom-right, bottom-left,
in pixels of the still), a corner ``radius`` and a ``bow`` for glass whose edges bulge
outward. ``find`` proposes corners by looking for the largest dark or bright four-sided area;
it is a starting point to look at, not a measurement.
"""
from __future__ import annotations

import cv2
import numpy as np

LOOKS = ("crt", "flat", "none")


def order_corners(points) -> np.ndarray:
    """Four points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(points, np.float32).reshape(4, 2)
    centre = pts.mean(0)
    pts = pts[np.argsort(np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0]))]   # clockwise in image coordinates
    return np.roll(pts, -int(np.argmin(pts.sum(1))), axis=0)


def find(image: np.ndarray) -> dict | None:
    """Guess where the screen is: the largest evenly lit area that is close to four-sided and stands out from what is round it.

    Returns ``{"corners": [[x, y] * 4], "fill": 0..1, "kind": "dark" | "bright"}`` or None.
    ``fill`` is how much of the four-sided outline the area fills. The guess is a place to start: draw it with
    ``outline`` and look before using it.
    """
    h, w = image.shape[:2]
    scale = 640.0 / max(h, w)
    small = cv2.resize(image, (max(8, int(w * scale)), max(8, int(h * scale))), interpolation=cv2.INTER_AREA)
    value = cv2.medianBlur(small.max(axis=2), 5)
    close, open_ = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    ring = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    found = []
    for level in range(30, 231, 10):
        for kind, mask in (("dark", value < level), ("bright", value > level)):
            m = cv2.morphologyEx(cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, close), cv2.MORPH_OPEN, open_)
            contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if not 0.02 * m.size < area < 0.65 * m.size:
                    continue
                x, y, cw, ch = cv2.boundingRect(contour)
                if x <= 1 or y <= 1 or x + cw >= m.shape[1] - 1 or y + ch >= m.shape[0] - 1:
                    continue  # touches the frame: a wall or a shadow, not a screen
                hull = cv2.convexHull(contour)
                quad = None
                for eps in np.linspace(0.01, 0.12, 23):
                    approx = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
                    if len(approx) == 4:
                        quad = order_corners(approx.reshape(4, 2))
                        break
                if quad is None:
                    continue
                fill = area / max(1.0, cv2.contourArea(quad))
                across = (np.linalg.norm(quad[1] - quad[0]) + np.linalg.norm(quad[2] - quad[3])) / 2
                down = (np.linalg.norm(quad[3] - quad[0]) + np.linalg.norm(quad[2] - quad[1])) / 2
                if not 0.84 <= fill <= 1.12 or not 0.6 <= across / max(1.0, down) <= 2.6:
                    continue
                body = np.zeros(m.shape, np.uint8)
                cv2.drawContours(body, [contour], -1, 1, -1)
                around = cv2.dilate(body, ring) - body
                contrast = abs(float(value[body > 0].mean()) - float(value[around > 0].mean()))
                if contrast < 14:
                    continue
                centre = quad.mean(0) / (m.shape[1], m.shape[0])
                score = area * min(fill, 1.0) ** 3 * min(contrast, 60.0) * (1.0 - 0.7 * float(np.hypot(*(centre - 0.5))))
                found.append((score, quad, min(fill, 1.0), kind, cv2.contourArea(quad)))
    if not found:
        return None
    best = max(found, key=lambda c: c[0])
    for _ in range(2):   # a screen sits inside its casing: prefer a good four-sided area nested in the one chosen
        inner = [c for c in found if 0.35 * best[4] <= c[4] <= 0.9 * best[4]
                 and all(cv2.pointPolygonTest(best[1], (float(x), float(y)), True) >= -4 for x, y in c[1])]
        if not inner:
            break
        best = max(inner, key=lambda c: c[0])
    return {"corners": [[round(float(x), 1), round(float(y), 1)] for x, y in best[1] / scale], "fill": round(float(best[2]), 3), "kind": best[3]}


class Screen:
    """One still with one screen in it, ready to show pictures on that screen."""

    def __init__(self, image: np.ndarray, corners, radius: float = 0.06, bow: float = 0.0, look: str = "crt",
                 spill: float = 0.6, neutral: float = 0.0, overscan: float = 0.03, work: float = 1.0):
        """``radius``: corner rounding as a fraction of the screen's height. ``bow``: how far each edge bulges
        outward at its middle, as a fraction of the screen's size. ``spill``: how strongly the picture lights the
        surroundings. ``neutral``: 0..1, how much of any colour cast already around the screen (from whatever it
        showed before) to remove. ``work``: the still is worked on at this multiple of its size."""
        if look not in LOOKS:
            raise ValueError(f"unknown screen look {look!r} (known: {', '.join(LOOKS)})")
        self.look, self.spill, self.k = look, float(spill), float(work)
        k = self.k
        if k != 1.0:
            image = cv2.resize(image, None, fx=k, fy=k, interpolation=cv2.INTER_LANCZOS4)
            if k > 1.5:
                image = cv2.addWeighted(image, 1.3, cv2.GaussianBlur(image, (0, 0), 0.7 * k), -0.3, 0)
        self.base = image.astype(np.float32)
        self.h, self.w = image.shape[:2]
        quad = order_corners(corners) * k
        self.corners = quad
        top, bottom = np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3])
        left, right = np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1])
        self.size = (float((top + bottom) / 2), float((left + right) / 2))          # the screen's width and height here, in pixels
        sw, sh = self.size
        aspect = sw / sh
        pad = int(np.ceil(max(sw, sh) * (float(bow) + 0.02))) + 3
        x0, y0 = np.floor(quad.min(0)).astype(int) - pad
        x1, y1 = np.ceil(quad.max(0)).astype(int) + pad
        self.box = (max(0, x0), max(0, y0), min(self.w, x1), min(self.h, y1))
        x0, y0, x1, y1 = self.box
        to_unit = cv2.getPerspectiveTransform(quad, np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]))
        gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        den = to_unit[2, 0] * gx + to_unit[2, 1] * gy + to_unit[2, 2]
        u = (to_unit[0, 0] * gx + to_unit[0, 1] * gy + to_unit[0, 2]) / den
        v = (to_unit[1, 0] * gx + to_unit[1, 1] * gy + to_unit[1, 2]) / den
        # edges that bulge: the middle of each edge reaches (1 + bow) times as far from the centre as its ends
        cu, cv_ = 2 * u - 1, 2 * v - 1
        u2 = cu / (1.0 + float(bow) * (1.0 - np.clip(cv_, -1, 1) ** 2))
        v2 = cv_ / (1.0 + float(bow) * (1.0 - np.clip(cu, -1, 1) ** 2))
        # distance to the rounded outline, in pixels (negative inside)
        r = float(np.clip(radius, 0.0, 0.5))
        qx, qy = np.abs(u2) * aspect / 2 - (aspect / 2 - r), np.abs(v2) / 2 - (0.5 - r)
        sdf = (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r) * sh
        self.alpha = np.clip(0.5 - sdf, 0.0, 1.0)[..., None].astype(np.float32)
        self.rw, self.rh = (int(min(1280, max(64, sw))), int(min(960, max(48, sh))))   # the raster the picture is drawn on
        over = 1.0 - float(overscan) if look == "crt" else 1.0
        self.map_x = ((u2 * over + 1) / 2 * (self.rw - 1)).astype(np.float32)
        self.map_y = ((v2 * over + 1) / 2 * (self.rh - 1)).astype(np.float32)
        inside = np.clip(-sdf / (0.055 * sh), 0.0, 1.0)
        self.rim = (0.45 + 0.55 * inside ** 0.7)[..., None].astype(np.float32) if look == "crt" else np.float32(1.0)
        bh, bw = y1 - y0, x1 - x0
        ry, rx = np.mgrid[0:bh, 0:bw].astype(np.float32)
        glare = np.exp(-(((rx - bw * 0.22) / (bw * 0.36)) ** 2 + ((ry - bh * 0.12) / (bh * 0.3)) ** 2))
        self.glare = (glare * (14.0 if look == "crt" else 5.0 if look == "flat" else 0.0))[..., None].astype(np.float32)
        lines = max(60, self.rh // 3)   # scanlines three raster rows apart at most, so they survive being scaled
        self.scan = (0.85 + 0.15 * np.cos(np.arange(self.rh) * np.pi * lines / self.rh) ** 2)[:, None, None].astype(np.float32)
        # the light the screen throws: strongest at its edge, gone a fraction of its height away
        full = np.zeros((self.h, self.w), np.uint8)
        full[y0:y1, x0:x1] = (self.alpha[..., 0] > 0.5).astype(np.uint8)
        outside = cv2.distanceTransform(1 - full, cv2.DIST_L2, 5)
        fall = (np.exp(-outside / (0.06 * sh)) * (1 - full))[..., None].astype(np.float32)
        luma = (self.base @ np.array([0.114, 0.587, 0.299], np.float32))[..., None]
        if neutral > 0:
            self.base = self.base * (1 - fall * float(neutral)) + luma * (fall * float(neutral))
        self.fall = fall * np.clip(luma / 170.0, 0.0, 1.3)   # brighter surfaces catch more of it

    def tube(self, picture: np.ndarray, t: float = 0.0, power: float = 1.0, snow: float = 0.0, seed: int = 0) -> np.ndarray:
        """The picture as the screen would show it, on the screen's own raster (float BGR)."""
        pic = cv2.resize(picture, (self.rw, self.rh), interpolation=cv2.INTER_AREA if picture.shape[1] > self.rw else cv2.INTER_CUBIC).astype(np.float32)
        if snow > 0:
            noise = np.random.default_rng(seed).integers(0, 255, (max(2, self.rh // 3), max(2, self.rw // 3), 1)).astype(np.float32)
            pic = pic * (1 - snow) + cv2.resize(np.repeat(noise, 3, 2), (self.rw, self.rh), interpolation=cv2.INTER_NEAREST) * snow
        if self.look == "none":
            return pic
        soft = self.rh / 720.0
        if self.look == "crt":
            pic = cv2.GaussianBlur(pic, (0, 0), max(0.3, 1.1 * soft))
            shift = max(1, int(round(2 * soft)))
            b, g, r = cv2.split(pic)
            pic = cv2.merge([np.roll(b, -shift, 1), g, np.roll(r, shift, 1)])
            pic = (pic - 16) * 1.16 + 10
        pic = pic + cv2.GaussianBlur(pic, (0, 0), max(1.0, 14 * soft)) * (0.28 if self.look == "crt" else 0.1)
        if self.look == "crt":
            band = 1.0 + 0.07 * np.exp(-(((np.arange(self.rh) / self.rh - (t * 0.9) % 1.3 + 0.15) / 0.09) ** 2))[:, None, None]
            pic = pic * self.scan * band * (1.0 + 0.018 * np.sin(t * 61.0))
        if power < 1:   # switching on: the picture opens from a bright line
            rows = max(3, int(self.rh * power))
            squeezed = cv2.resize(pic, (self.rw, rows))
            pic = np.full_like(pic, 6.0)
            a = (self.rh - rows) // 2
            pic[a:a + rows] = squeezed * (1 + 3.0 * (1 - power))
        return np.clip(pic, 0, 255)

    def show(self, picture: np.ndarray | None, **tube) -> np.ndarray:
        """The whole still with ``picture`` on its screen, or the screen dark if None. Float BGR at working size."""
        x0, y0, x1, y1 = self.box
        out = self.base.copy()
        if picture is None:
            face = np.full((y1 - y0, x1 - x0, 3), (20.0, 22.0, 20.0), np.float32) * self.rim + self.glare * 1.5
        else:
            face = cv2.remap(self.tube(picture, **tube), self.map_x, self.map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            if self.spill > 0:
                glow = (face * self.alpha).reshape(-1, 3).sum(0) / max(1.0, float(self.alpha.sum()))
                out += self.fall * glow * (1.05 * self.spill)
            face = face * self.rim + self.glare
        out[y0:y1, x0:x1] = face * self.alpha + out[y0:y1, x0:x1] * (1 - self.alpha)
        return out

    def centre(self) -> tuple[float, float]:
        """The middle of the screen, in pixels of the original still."""
        c = self.corners.mean(0) / self.k
        return float(c[0]), float(c[1])


def view(canvas: np.ndarray, k: float, centre: tuple[float, float], across: float, size: tuple[int, int]) -> np.ndarray:
    """What a camera centred on ``centre`` (pixels of the original still) and seeing ``across`` of those pixels frames."""
    w, h = size
    s = w / (across * k)
    if s < 0.95:
        canvas = cv2.GaussianBlur(canvas, (0, 0), 0.5 / s - 0.3)
    m = np.float32([[s, 0, w / 2 - centre[0] * k * s], [0, s, h / 2 - centre[1] * k * s]])
    return cv2.warpAffine(canvas, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def frames(image: np.ndarray, corners, pictures, count: int, size: tuple[int, int], fps: float, push: tuple[float, float] = (1.0, 1.6),
           power_on: bool = True, settle: float = 0.28, **screen):
    """Yield ``count`` frames (uint8 BGR, ``size``) of the still with ``pictures`` playing on its screen.

    ``pictures`` is an iterator of BGR frames at ``fps``; when it runs out the last one is held. ``push`` is the
    camera's magnification at the first and last frame, where 1.0 shows as much of the still as fits the frame.
    The move starts fast and settles (``settle`` is the fraction of the shot the first 63% of it takes), and the
    camera travels from the middle of the still to the middle of the screen as it goes in.
    """
    w, h = size
    ih, iw = image.shape[:2]
    fit = min(iw, ih * w / h)                                  # how many pixels of the still a frame can show across
    closest = fit / max(push)
    work = float(np.clip(np.ceil(w / closest * 2) / 2, 1.0, 4.0))   # enough working pixels for the closest framing
    scr = Screen(image, corners, work=work, **screen)
    cx, cy = scr.centre()
    pictures = iter(pictures)
    last = None
    tau = max(1e-3, settle)
    for i in range(count):
        t = i / fps
        nxt = next(pictures, None)
        last = nxt if nxt is not None else last
        lit = not power_on or t >= 0.06
        canvas = scr.show(last if lit else None, t=t, power=min(1.0, max(0.02, (t - 0.06) / 0.2)) if power_on else 1.0,
                          snow=0.5 if power_on and 0.06 <= t < 0.15 else 0.0, seed=i)
        p = (1 - np.exp(-(i / max(1, count - 1)) / tau)) / (1 - np.exp(-1 / tau))
        zoom = push[0] + (push[1] - push[0]) * p
        across = fit / zoom
        half_w, half_h = across / 2, across * h / w / 2
        x = np.clip(iw / 2 + (cx - iw / 2) * p, half_w, max(half_w, iw - half_w))
        y = np.clip(ih / 2 + (cy - ih / 2) * p, half_h, max(half_h, ih - half_h))
        yield np.clip(view(canvas, scr.k, (float(x), float(y)), across, size), 0, 255).astype(np.uint8)


def outline(image: np.ndarray, corners, radius: float = 0.06, bow: float = 0.0) -> np.ndarray:
    """The still with the screen's outline drawn on it, to check the corners by eye."""
    scr = Screen(image, corners, radius=radius, bow=bow, look="none", spill=0.0)
    x0, y0, x1, y1 = scr.box
    out = image.copy()
    edge = cv2.Canny((scr.alpha[..., 0] * 255).astype(np.uint8), 50, 150)
    edge = cv2.dilate(edge, np.ones((max(2, image.shape[1] // 600), max(2, image.shape[1] // 600)), np.uint8))
    region = out[y0:y1, x0:x1]
    region[edge > 0] = (0, 0, 255)
    for i, (x, y) in enumerate(order_corners(corners)):
        cv2.circle(out, (int(x), int(y)), max(4, image.shape[1] // 200), (0, 255, 255), -1)
        cv2.putText(out, "TL TR BR BL".split()[i], (int(x) + 8, int(y) - 8), cv2.FONT_HERSHEY_SIMPLEX, max(0.5, image.shape[1] / 1600), (0, 255, 255), 2)
    return out
