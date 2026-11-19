"""Finishing: what leaves the project after the cut is locked.

* ``loop``    a version whose end hands back to its start, for players that repeat.
* ``cover``   a still for the post: a frame you name, or the one that scores best for
              sharpness, colour and exposure. The score knows nothing about meaning.
* ``deliver`` a smaller file for uploading, with a ceiling on its bitrate.
"""
from __future__ import annotations

import subprocess
import tempfile
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from . import ff

SR = 48000


def loop(source: Path, target: Path, over: float = 0.5) -> dict:
    """Write ``target``: ``source`` without its first ``over`` seconds, ending in a dissolve back into them."""
    info = ff.probe(source)
    fps, size = info["fps"], (info["width"], info["height"])
    n = max(2, int(round(over * fps)))
    if info["duration"] < 4 * n / fps:
        raise ValueError("the film is too short to loop with that overlap")
    reader = ff.FrameReader(source, 0.0, fps, size)
    head = [reader.read() for _ in range(n)]
    with tempfile.TemporaryDirectory() as folder:
        picture, sound = Path(folder) / "picture.mp4", Path(folder) / "sound.wav"
        writer = ff.FrameWriter(picture, size, fps, 16, "medium")
        held: deque = deque()
        written = 0
        while (frame := reader.read()) is not None:
            held.append(frame)
            if len(held) > n:
                writer.write(held.popleft())
                written += 1
        reader.close()
        for j, frame in enumerate(held):  # the last frames turn into the first ones
            k = (j + 1) / (len(held) + 1)
            writer.write(cv2.addWeighted(frame, 1.0 - k, head[min(j, n - 1)], k, 0))
            written += 1
        writer.close()
        audio = None
        if info.get("has_audio"):
            x = ff.read_audio(source, SR, 2).astype(np.float64)
            m = min(int(n / fps * SR), len(x) // 4)
            ramp = np.linspace(0.0, np.pi / 2, m)[:, None]
            tail = x[-m:] * np.cos(ramp) + x[:m] * np.sin(ramp)  # equal-power: no dip, no bump
            ff.write_wav(sound, np.concatenate([x[m:-m], tail]), SR)
            audio = sound
        ff.concat_copy([picture], Path(target), audio)
    return {"frames": written, "duration": round(written / fps, 3), "overlap_frames": n}


def best_frame(source: Path, samples: int = 48) -> float:
    """The time of the sampled frame that is sharpest, most colourful and best exposed."""
    info = ff.probe(source)
    times = np.linspace(0.04, 0.96, samples) * info["duration"]
    rows = []
    for t in times:
        frame = ff.grab_frame(source, float(t), 480)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32) / 255.0
        luma = float(hsv[..., 2].mean())
        rows.append((float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_32F).var()),
                     float(hsv[..., 1].mean()), max(0.05, 1.0 - 1.6 * abs(luma - 0.45))))
    sharp = np.array([r[0] for r in rows])
    score = (sharp / (sharp.max() + 1e-9)) ** 0.5 * (0.4 + np.array([r[1] for r in rows])) * np.array([r[2] for r in rows])
    return round(float(times[int(np.argmax(score))]), 3)


def cover(source: Path, target: Path, at: float | None = None) -> float:
    at = best_frame(source) if at is None else float(at)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), ff.grab_frame(source, at), [cv2.IMWRITE_JPEG_QUALITY, 93])
    return at


def deliver(source: Path, target: Path, mbps: float = 10.0) -> dict:
    """Re-encode for upload: H.264 High, 4:2:0, a keyframe every two seconds, AAC, bitrate held under ``mbps``."""
    info = ff.probe(source)
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-c:v", "libx264", "-preset", "slow", "-crf", "18",
               "-maxrate", f"{mbps}M", "-bufsize", f"{2 * mbps}M", "-pix_fmt", "yuv420p", "-profile:v", "high",
               "-g", str(int(round(info["fps"] * 2))), "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(target)]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError("ffmpeg could not write the upload file: " + done.stderr.strip()[-400:])
    return {"bytes": Path(target).stat().st_size, "was": Path(source).stat().st_size, "duration": ff.probe(target)["duration"]}
