"""Voice treatment: making a voice sit in a mix, and making it an event.

Three tools, all plain signal processing:

* ``treat`` shapes one voice: a rumble filter, a lift where consonants live, gentle
  levelling, and optionally a room. Presets: ``clear`` (intelligible, nearly dry),
  ``hall`` (the same voice in a large space, for weight) and ``radio`` (narrow and
  driven, like an old broadcast).
* ``carve`` turns the music down only where speech needs the room (roughly 300 Hz to
  4 kHz) and only while someone is speaking, so the low end and the air of the track
  stay up under the voice.
* ``throw`` repeats a word into the gap after it, in time with the music.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, fftconvolve, sosfilt, sosfiltfilt

PRESETS = {
    "clear": {"hp": 90, "presence_db": 3.0, "mud_db": -2.0, "comp": 3.0, "reverb": 0.05, "tail": 0.7},
    "hall": {"hp": 90, "presence_db": 2.0, "mud_db": -2.0, "comp": 3.0, "reverb": 0.24, "tail": 2.4, "predelay": 0.03},
    "radio": {"hp": 300, "lp": 3400, "presence_db": 4.0, "mud_db": 0.0, "comp": 5.0, "drive": 2.5, "reverb": 0.0, "tail": 0.0},
}
SPEECH_BAND = (300.0, 4000.0)


def settings(treat) -> dict | None:
    """Resolve a voice entry's ``treat`` value (a preset name, or a dict that may name a preset) to full settings."""
    if not treat or treat == "none":
        return None
    if isinstance(treat, str):
        if treat not in PRESETS:
            raise ValueError(f"unknown voice treatment {treat!r} (known: {', '.join(PRESETS)}, none)")
        return dict(PRESETS[treat])
    base = dict(PRESETS[treat.get("preset", "clear")]) if treat.get("preset", "clear") in PRESETS else {}
    return {**base, **{k: v for k, v in treat.items() if k != "preset"}}


def _peak(x: np.ndarray, sr: int, freq: float, gain_db: float, q: float = 0.9) -> np.ndarray:
    """A bell boost or cut at ``freq`` (RBJ peaking filter)."""
    if abs(gain_db) < 0.05:
        return x
    a, w = 10.0 ** (gain_db / 40.0), 2.0 * np.pi * freq / sr
    alpha = np.sin(w) / (2.0 * q)
    b = np.array([1 + alpha * a, -2 * np.cos(w), 1 - alpha * a])
    den = np.array([1 + alpha / a, -2 * np.cos(w), 1 - alpha / a])
    return sosfilt(np.r_[b / den[0], 1.0, den[1:] / den[0]][None, :], x)


def _level(x: np.ndarray, sr: int, ratio: float) -> np.ndarray:
    """Even out a voice: loud syllables come down toward the body of the speech, then the whole is brought back up."""
    env = np.sqrt(np.maximum(uniform_filter1d(x ** 2, size=int(0.02 * sr)), 0.0))
    level = 20.0 * np.log10(env + 1e-9)
    speaking = level[level > level.max() - 40.0]
    if ratio <= 1.0 or not len(speaking):
        return x
    threshold = float(np.percentile(speaking, 45))
    reduce = -np.maximum(0.0, level - threshold) * (1.0 - 1.0 / ratio)
    reduce = uniform_filter1d(minimum_filter1d(reduce, size=int(0.005 * sr)), size=int(0.06 * sr))
    out = x * 10.0 ** (reduce / 20.0)
    before, after = np.sqrt(np.mean(x ** 2)), np.sqrt(np.mean(out ** 2))
    return out * min(4.0, before / (after + 1e-12))


def room(sr: int, tail: float, seed: int = 11) -> np.ndarray:
    """A synthetic stereo room response: a few early reflections, then diffuse noise dying away over ``tail`` seconds."""
    n = max(1, int(tail * sr))
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    body = rng.normal(0.0, 1.0, (n, 2)) * np.exp(-6.9 * t / max(tail, 1e-3))[:, None]
    body *= np.minimum(1.0, t / 0.02)[:, None]  # the diffuse field arrives a moment after the direct sound
    for k in range(6):
        body[min(n - 1, int(rng.uniform(0.008, 0.07) * sr)), k % 2] += rng.uniform(0.3, 0.7) * (-1) ** k * 12.0
    body = sosfiltfilt(butter(2, [220, 6500], "bandpass", fs=sr, output="sos"), body, axis=0)
    return body / (np.sqrt((body ** 2).sum(0)).mean() + 1e-12)


def treat(x: np.ndarray, sr: int, spec: dict) -> np.ndarray:
    """Process one mono voice. Returns stereo, longer than the input by the room's tail."""
    x = np.asarray(x, np.float64)
    if spec.get("hp"):
        x = sosfilt(butter(2, float(spec["hp"]), "highpass", fs=sr, output="sos"), x)
    if spec.get("lp"):
        x = sosfilt(butter(4, float(spec["lp"]), "lowpass", fs=sr, output="sos"), x)
    x = _peak(_peak(x, sr, 320.0, float(spec.get("mud_db", 0.0)), 1.0), sr, 3200.0, float(spec.get("presence_db", 0.0)))
    x = _level(x, sr, float(spec.get("comp", 1.0)))
    if spec.get("drive"):
        d = float(spec["drive"])
        x = np.tanh(x * d) / np.tanh(d) * np.abs(x).max() / (np.abs(np.tanh(x * d) / np.tanh(d)).max() + 1e-12)
    wet, tail = float(spec.get("reverb", 0.0)), float(spec.get("tail", 0.0))
    dry = np.repeat(x[:, None], 2, axis=1)
    if wet <= 0 or tail <= 0:
        return dry
    out = np.zeros((len(x) + int((tail + float(spec.get("predelay", 0.015))) * sr), 2))
    out[:len(x)] = dry
    start = int(float(spec.get("predelay", 0.015)) * sr)
    ir = room(sr, tail)
    for ch in (0, 1):
        tail_audio = fftconvolve(x, ir[:, ch])[:len(out) - start]
        out[start:start + len(tail_audio), ch] += wet * tail_audio
    return out


def carve(music: np.ndarray, active: np.ndarray, sr: int, depth_db: float) -> np.ndarray:
    """Lower the speech band of the music by up to ``depth_db`` wherever ``active`` (0..1 per sample) says someone is speaking."""
    if depth_db >= 0 or not active.any():
        return music
    band = sosfiltfilt(butter(2, SPEECH_BAND, "bandpass", fs=sr, output="sos"), music, axis=0)
    gain = 10.0 ** (depth_db * active / 20.0)
    return music + band * (gain - 1.0)[:, None]


def throw(bus: np.ndarray, sr: int, at: float, dur: float, delay: float, repeats: int = 3, feedback: float = 0.5,
          level_db: float = -5.0) -> np.ndarray:
    """Echo the stretch of ``bus`` starting at ``at`` into the time after it. Returns what to add (same shape as bus)."""
    out = np.zeros_like(bus)
    a, n = int(at * sr), int(dur * sr)
    word = bus[a:a + n].copy()
    if not len(word) or delay <= 0:
        return out
    fade = min(len(word) // 2, int(0.01 * sr))
    if fade:
        ramp = np.linspace(0.0, 1.0, fade)
        word[:fade] *= ramp[:, None]
        word[-fade:] *= ramp[::-1, None]
    gain = 10.0 ** (level_db / 20.0)
    for k in range(1, repeats + 1):
        echo = sosfilt(butter(2, max(900.0, 5200.0 * 0.62 ** (k - 1)), "lowpass", fs=sr, output="sos"), word, axis=0) * gain
        pan = 0.25 if k % 2 else 0.75  # alternate sides
        echo = np.stack([echo.mean(1) * np.cos(pan * np.pi / 2) * 1.41, echo.mean(1) * np.sin(pan * np.pi / 2) * 1.41], axis=1)
        start = a + int(k * delay * sr)
        end = min(len(out), start + len(echo))
        if start < len(out):
            out[start:end] += echo[:end - start]
        gain *= feedback
    return out
