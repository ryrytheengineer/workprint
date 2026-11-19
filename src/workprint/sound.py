"""Designed sounds, synthesised from first principles.

A small kit of accents for cutting to music: impacts, risers, whooshes. They are
generated rather than sampled so the repository ships no third-party audio, every
sound is deterministic, and low elements can be tuned to the key of the music.
An editor's own sound effects can be used instead via ``{"file": ...}`` entries.

Every generator returns ``(audio, lead)``: stereo float samples at 48 kHz and the
number of seconds of the sound that come *before* its hit point.
"""
from __future__ import annotations

import zlib

import numpy as np
from scipy import signal

SR = 48000


def db(x: float) -> float:
    return 10.0 ** (x / 20.0)


def root_hz(pitch_class: int | None) -> float:
    """Frequency of a pitch class placed in the sub range (about 37 to 69 Hz). Defaults to A."""
    f = 32.703 * 2.0 ** ((9 if pitch_class is None else pitch_class) / 12.0)
    return f * 2 if f < 36.5 else f


def _t(n: int) -> np.ndarray:
    return np.arange(n) / SR


def _osc(freq: np.ndarray) -> np.ndarray:
    return np.sin(2 * np.pi * np.cumsum(freq) / SR)


def _decay(n: int, attack: float, tau: float) -> np.ndarray:
    env = np.exp(-_t(n) / tau)
    a = max(1, int(attack * SR))
    env[:a] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    return env


def _band(x: np.ndarray, lo: float | None, hi: float | None, order: int = 2) -> np.ndarray:
    if lo and hi:
        sos = signal.butter(order, [lo, hi], "bandpass", fs=SR, output="sos")
    elif lo:
        sos = signal.butter(order, lo, "highpass", fs=SR, output="sos")
    else:
        sos = signal.butter(order, hi, "lowpass", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0)


def _drive(x: np.ndarray, amount: float) -> np.ndarray:
    return np.tanh(x * amount) / np.tanh(amount)


def _tail(x: np.ndarray, seconds: float) -> np.ndarray:
    k = min(len(x), int(seconds * SR))
    w = 0.5 + 0.5 * np.cos(np.pi * np.arange(k) / k)
    x = x.copy()
    x[-k:] *= w if x.ndim == 1 else w[:, None]
    return x


def _level(x: np.ndarray, level_db: float) -> np.ndarray:
    return x / (np.abs(x).max() + 1e-12) * db(level_db)


def _stereo(x: np.ndarray) -> np.ndarray:
    return np.stack([x, x], 1) if x.ndim == 1 else x


def _sweep_noise(rng, n: int, f0: float, f1: float, shape: np.ndarray, channels: int = 1) -> np.ndarray:
    """Noise through a one-pole low-pass whose cutoff glides from f0 to f1."""
    noise = rng.standard_normal((n, channels))
    cutoff = f0 * (f1 / f0) ** shape
    alpha = 1.0 - np.exp(-2 * np.pi * cutoff / SR)
    out = np.zeros_like(noise)
    state = np.zeros(channels)
    for i in range(n):
        state += alpha[i] * (noise[i] - state)
        out[i] = state
    return _band(out, 250, None)


def impact(rng, root: float, weight: float = 1.0):
    """A heavy hit: tuned sub, a body an octave up, a short slam and a low stereo rumble."""
    n = int((1.2 + 0.5 * weight) * SR)
    t = _t(n)
    sub = _drive(_osc(root + 2 * root * np.exp(-t / 0.022)) * _decay(n, 0.002, 0.30 * weight + 0.08), 2.2)
    body = _osc(np.full(n, root * 2)) * _decay(n, 0.002, 0.085)
    rumble = _band(rng.standard_normal((n, 2)), 35, 160, 4) * _decay(n, 0.01, 0.42)[:, None]
    k = int(0.09 * SR)
    slam = np.zeros(n)
    slam[:k] = _band(rng.standard_normal(k), 150, 2500) * np.exp(-_t(k) / 0.016)
    mix = _stereo(_level(sub, 0) + _level(body, -7) + _level(slam, -10)) + _level(rumble, -12)
    return _tail(mix, 0.4), 0.0


def sub(rng, root: float, weight: float = 1.0):
    """A short, dry low knock."""
    n = int(0.6 * SR)
    x = _drive(_osc(root + 2 * root * np.exp(-_t(n) / 0.018)) * _decay(n, 0.002, 0.13 * weight), 2.0)
    return _stereo(_tail(x, 0.2)), 0.0


def boom(rng, root: float, weight: float = 1.0):
    """A long low boom for endings and title cards."""
    n = int(2.4 * SR)
    t = _t(n)
    x = _osc(root * 0.5 + root * 0.6 * np.exp(-t * 9)) * np.exp(-t / 0.5)
    return _stereo(_tail(x, 0.5)), 0.0


def riser(rng, root: float, weight: float = 1.0, duration: float = 3.0):
    """Filtered noise and a tone climbing into the hit point, then stopping dead."""
    n = int(duration * SR)
    p = _t(n) / duration
    noise = _sweep_noise(rng, n, 300, 9000, p, 2) * (p ** 2.2)[:, None]
    tone = _osc(root * 2 * 4.0 ** p) * p ** 3
    mix = _level(noise, 0) + _stereo(_level(tone, -9))
    return _tail(mix, 0.03), duration


def downlifter(rng, root: float, weight: float = 1.0, duration: float = 1.2):
    """A note falling two octaves into the hit point: tension before a drop."""
    n = int(duration * SR)
    p = _t(n) / duration
    x = _drive(_osc(root * 4 * 0.25 ** p) * (0.3 + 0.7 * p ** 1.4), 2.0)
    x[: int(0.015 * SR)] *= np.linspace(0, 1, int(0.015 * SR))
    return _stereo(_tail(x, 0.03)), duration


def whoosh(rng, root: float, weight: float = 1.0, duration: float = 0.45):
    """Air moving left to right that peaks on the hit point."""
    after = 0.16
    n = int((duration + after) * SR)
    t = _t(n)
    x = _sweep_noise(rng, n, 350, 4500, np.clip(t / duration, 0, 1))[:, 0]
    x *= np.where(t < duration, (t / duration) ** 2.2, np.exp(-(t - duration) / 0.045))
    pan = np.clip(t / (duration + after), 0, 1) * np.pi / 2
    return np.stack([x * np.cos(pan), x * np.sin(pan)], 1), duration


def swell(rng, root: float, weight: float = 1.0, duration: float = 0.7):
    """A reverse swell that opens into the hit point."""
    n = int(duration * SR)
    x = _band(rng.standard_normal((n, 2)), 500, 6000) * ((_t(n) / duration) ** 3)[:, None]
    return _tail(x, 0.02), duration


def tick(rng, root: float, weight: float = 1.0):
    """A small dry tick for light accents."""
    n = int(0.08 * SR)
    x = _band(rng.standard_normal(n), 700, 4200) * np.exp(-_t(n) / 0.016)
    return _stereo(x), 0.0


KIT = {"impact": impact, "sub": sub, "boom": boom, "riser": riser, "downlifter": downlifter, "whoosh": whoosh,
       "swell": swell, "tick": tick}
# Loudness of each sound relative to the level asked for, so that "db" means roughly the same weight for all.
TRIM = {"impact": 0.0, "sub": 0.0, "boom": 0.0, "riser": -4.0, "downlifter": -2.0, "whoosh": -6.0, "swell": -6.0, "tick": -8.0}


def make(spec: dict, key_root: int | None = None):
    """Build one sound from a cut's ``sounds`` entry. Returns (stereo audio, lead seconds)."""
    kind = spec["kind"]
    seed = zlib.crc32(f"{spec.get('id', '')}:{kind}".encode())
    pitch = spec.get("pitch", key_root)
    kwargs = {"duration": float(spec["dur"])} if "dur" in spec and kind in ("riser", "downlifter", "whoosh", "swell") else {}
    audio, lead = KIT[kind](np.random.default_rng(seed), root_hz(pitch), float(spec.get("weight", 1.0)), **kwargs)
    return _level(_stereo(audio), float(spec.get("db", -12.0)) + TRIM[kind]), lead
