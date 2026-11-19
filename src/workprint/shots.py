"""Footage analysis: shot boundaries and measurable facts about each shot.

One low-resolution decode per source yields, per frame, a colour-histogram distance
and a mean absolute difference to the previous frame, a global camera shift
(phase correlation) and basic exposure statistics. Cuts are found with an adaptive
threshold on the histogram distance: a frame starts a new shot when its distance is
high in absolute terms and stands well above its neighbourhood, which keeps fast
action and camera moves from being mistaken for cuts.

These are standard techniques; the implementation is Workprint's own. Gradual
transitions (dissolves) inside a source are not detected.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from . import ff

AW, AH = 160, 90  # analysis resolution
MIN_CHANGE = 0.003  # a cut must change the picture by at least this mean absolute difference (0-1)


def frame_signals(path, info: dict, start: float = 0.0, duration: float | None = None) -> dict:
    """Per-frame signals for a source at its own frame rate."""
    fps = info["fps"] or 24.0
    hist_d, diff, shift, luma, sat, contrast, peak = [], [], [], [], [], [], []
    window = cv2.createHanningWindow((AW, AH), cv2.CV_32F)
    prev_gray = prev_hist = None
    limit = int(round(duration * fps)) if duration else None
    with ff.FrameReader(path, start, fps, (AW, AH), matrix=info.get("matrix", "bt709"), scaler="area") as reader:
        while True:
            frame = reader.read()
            if frame is None or (limit is not None and reader.frames_read > limit):
                break
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
            # Luma/chroma histogram with an odd number of chroma bins: neutral and near-black pixels sit in the
            # middle of a bin, so noise in dark footage does not flip them between bins (hue would).
            ycc = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
            hist = cv2.calcHist([ycc], [0, 1, 2], None, [8, 5, 5], [0, 256, 0, 256, 0, 256]).ravel()
            hist /= max(hist.sum(), 1.0)
            if prev_gray is None:
                hist_d.append(0.0); diff.append(0.0); shift.append(0.0)
            else:
                hist_d.append(float(np.abs(hist - prev_hist).sum()) * 0.5)
                diff.append(float(np.abs(gray - prev_gray).mean()) / 255.0)
                # copies: some OpenCV builds apply the window to their inputs in place
                (dx, dy), response = cv2.phaseCorrelate(prev_gray.copy(), gray.copy(), window)
                shift.append(float(np.hypot(dx, dy)) / AW if response > 0.05 else 0.0)
            luma.append(float(gray.mean()) / 255.0)
            peak.append(float(np.partition(gray.ravel(), -72)[-72]) / 255.0)  # brightness of the brightest half percent
            contrast.append(float(gray.std()) / 255.0)
            sat.append(float(hsv[..., 1].mean()) / 255.0)
            prev_gray, prev_hist = gray, hist
    return {"fps": fps, "hist": np.array(hist_d), "diff": np.array(diff), "shift": np.array(shift),
            "luma": np.array(luma), "sat": np.array(sat), "contrast": np.array(contrast), "peak": np.array(peak)}


def find_cuts(hist: np.ndarray, diff: np.ndarray, fps: float, floor: float = 0.14, ratio: float = 3.0,
              min_len: float = 0.25) -> list[int]:
    """Frame indices where a new shot starts.

    A frame is a cut when its histogram distance is a local maximum that clears an absolute
    floor and stands ``ratio`` times above the median of its neighbourhood. A second rule
    catches cuts between shots of similar colour: a modest histogram change together with a
    pixel difference that spikes above its own neighbourhood.
    Either way the frame must differ from the one before it by MIN_CHANGE, which keeps noise in
    very dark footage from registering as cuts.
    """
    n = len(hist)
    if n < 3:
        return []
    radius = max(4, int(round(fps * 0.4)))
    cuts: list[int] = []
    for i in range(1, n):
        if hist[i] < 0.06 or diff[i] < MIN_CHANGE:
            continue
        lo, hi = max(1, i - radius), min(n, i + radius + 1)
        if hist[i] < hist[lo:hi].max() - 1e-9:
            continue
        around_h = np.concatenate([hist[lo:i], hist[i + 1:hi]])
        around_d = np.concatenate([diff[lo:i], diff[i + 1:hi]])
        base_h = float(np.median(around_h)) if len(around_h) else 0.0
        base_d = float(np.median(around_d)) if len(around_d) else 0.0
        strong = hist[i] >= max(floor, ratio * base_h + 0.04)
        similar_colour = hist[i] >= ratio * base_h + 0.03 and diff[i] >= max(4.0 * base_d, base_d + 0.02)
        if strong or similar_colour:
            cuts.append(i)
    # A flash or a single odd frame produces two boundaries a frame or two apart: keep the first.
    gap = max(2, int(round(min_len * fps)))
    merged: list[int] = []
    for c in cuts:
        if not merged or c - merged[-1] >= gap:
            merged.append(c)
    return merged


def _calm_window(curve: np.ndarray, length: int) -> int:
    """Start index of the window of ``length`` samples with the least activity."""
    if len(curve) <= length:
        return 0
    sums = np.convolve(curve, np.ones(length), "valid")
    return int(np.argmin(sums))


def describe_shots(source: dict, signals: dict, cuts: list[int]) -> list[dict]:
    """Turn frame signals and cut positions into shot log entries."""
    fps = signals["fps"]
    n = len(signals["hist"])
    bounds = [0] + cuts + [n]
    shots = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        if b - a < 2:
            continue
        # Skip the first frame of the shot in activity stats: it carries the cut itself.
        seg = slice(min(a + 1, b - 1), b)
        motion = signals["diff"][seg]
        step = max(1, int(round(fps / 4)))
        curve = [round(float(motion[i:i + step].mean()) * 100, 2) for i in range(0, len(motion), step)]
        calm = _calm_window(np.array(curve), min(len(curve), 8)) * step / fps
        luma = float(signals["luma"][a:b].mean())
        shots.append({
            "id": f"{source['id']}-{len(shots) + 1:02d}", "src": source["id"],
            "start": round(a / fps, 3), "end": round(b / fps, 3), "dur": round((b - a) / fps, 3),
            "motion": round(float(motion.mean()) * 100, 2), "camera": round(float(signals["shift"][seg].mean()) * 100, 2),
            "luma": round(luma, 3), "contrast": round(float(signals["contrast"][a:b].mean()), 3),
            "sat": round(float(signals["sat"][a:b].mean()), 3),
            "peak": round(float(np.argmax(motion)) / fps, 2), "calm": round(calm, 2), "curve": curve,
            # Black means nothing bright anywhere: a night shot with a few lights is dark, not black.
            "black": bool(luma < 0.035 and float(signals["peak"][a:b].mean()) < 0.10), "desc": "", "tags": [], "rating": None,
        })
    return shots


def analyze_source(project, source: dict) -> list[dict]:
    path = project.path_of(source)
    signals = frame_signals(path, source)
    cuts = find_cuts(signals["hist"], signals["diff"], signals["fps"])
    return describe_shots(source, signals, cuts)


def ingest(project, progress=print) -> list[dict]:
    """Analyse every source not yet in the shot log; keep existing notes untouched."""
    existing = project.shots()
    done = {s["src"] for s in existing}
    shots = list(existing)
    for source in project.data["sources"]:
        if source["id"] in done:
            continue
        found = analyze_source(project, source)
        progress(f"{source['id']}  {Path(source['path']).name}: {len(found)} shot(s), {source['duration']:.1f}s")
        shots += found
    project.save_shots(shots)
    return shots


def shot_by_id(shots: list[dict], shot_id: str) -> dict:
    for shot in shots:
        if shot["id"] == shot_id:
            return shot
    raise KeyError(f"unknown shot {shot_id!r}")


def shot_at(shots: list[dict], src: str, t: float) -> dict | None:
    """The logged shot of a source that contains source time ``t``."""
    for shot in shots:
        if shot["src"] == src and shot["start"] - 1e-6 <= t < shot["end"] - 1e-6:
            return shot
    return None
