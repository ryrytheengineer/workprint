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


def screen_on(rng, root: float, weight: float = 1.0):
    """An old screen switching on: a relay thunk, the degauss hum, a burst of static, the whine settling."""
    n = int(1.1 * SR)
    t = _t(n)
    thunk = np.sin(2 * np.pi * 70 * t) * _decay(n, 0.001, 0.0125) * 1.2
    hum_ = np.sin(2 * np.pi * 120 * t + 3 * np.sin(2 * np.pi * 9 * t)) * _decay(n, 0.01, 0.09) * 0.6
    static_ = _band(rng.standard_normal(n), 1500, 9000) * _decay(n, 0.002, 0.03) * 0.7
    whine = np.sin(2 * np.pi * (6000 + 9600 * np.minimum(1.0, t / 0.25)) * t) * _decay(n, 0.02, 0.125) * 0.05
    return _stereo(_tail(thunk + hum_ + static_ + whine, 0.05)), 0.0


def static(rng, root: float, weight: float = 1.0):
    """A short smack of static: a channel change, a bad connection."""
    n = int(0.22 * SR)
    x = _band(rng.standard_normal(n), 900, 10000) * _decay(n, 0.001, 0.0175) + np.sin(2 * np.pi * 55 * _t(n)) * _decay(n, 0.001, 0.01)
    return _stereo(_tail(x, 0.02)), 0.0


def key(rng, root: float, weight: float = 1.0):
    """One soft key strike, for words that appear one at a time."""
    n = int(0.06 * SR)
    x = _band(rng.standard_normal(n), 1800, 7000) * _decay(n, 0.0005, 0.002) + np.sin(2 * np.pi * 2300 * _t(n)) * _decay(n, 0.0005, 0.0015) * 0.4
    return _stereo(x), 0.0


def shutter(rng, root: float, weight: float = 1.0):
    """A camera shutter: two clicks close together. For fast cuts between stills or short shots."""
    n = int(0.16 * SR)
    x = np.zeros(n)
    for offset, gain in ((0.0, 1.0), (0.055, 0.7)):
        k = int(offset * SR)
        x[k:] += _band(rng.standard_normal(n - k), 1200, 6000) * _decay(n - k, 0.0005, 0.003) * gain
    return _stereo(x), 0.0


def rocket(rng, root: float, weight: float = 1.0, duration: float = 7.0):
    """A low roar with crackle that starts hard and dies away: engines, fire, anything large burning."""
    n = int(duration * SR)
    t = _t(n)
    brown = np.cumsum(rng.standard_normal(n))
    roar = _band(brown - _band(brown, None, 20), 28, 160, 4)
    roar /= np.abs(roar).max() + 1e-12
    gate = signal.lfilter([1.0], [1.0, -0.9995], (rng.random(n) > 0.9992).astype(float))
    crackle = _band(rng.standard_normal(n), 250, 2600, 4) * np.minimum(1.0, gate)
    crackle /= np.abs(crackle).max() + 1e-12
    shape = np.minimum(1.0, t / 0.08) * np.exp(-t / (duration * 0.46))
    x = (roar * (0.85 + 0.15 * np.sin(2 * np.pi * 7 * t)) + 0.55 * crackle) * shape
    return np.stack([x, np.roll(x, int(0.004 * SR))], 1), 0.0


def blast(rng, root: float, weight: float = 1.0):
    """An explosion: a crack, then a long low tail."""
    n = int(2.6 * SR)
    t = _t(n)
    crack = _band(rng.standard_normal(n), 400, 7000, 4) * _decay(n, 0.001, 0.0125)
    body = _band(np.cumsum(rng.standard_normal(n)), 25, 220, 4)
    body /= np.abs(body).max() + 1e-12
    thud = np.sin(2 * np.pi * (60 - 22 * np.minimum(1.0, t / 0.6)) * t) * _decay(n, 0.002, 0.125)
    return _stereo(_tail(crack * 0.8 + body * _decay(n, 0.004, 0.225) + thud, 0.3)), 0.0


def beep(rng, root: float, weight: float = 1.0):
    """A radio tone, like the one that brackets a mission-control call."""
    n = int(0.26 * SR)
    return _stereo(_tail(np.sin(2 * np.pi * 2525 * _t(n)) * _decay(n, 0.004, 10.0), 0.01)), 0.0


def reverse(rng, root: float, weight: float = 1.0, duration: float = 1.3):
    """Air rushing up to a cut and stopping dead on it."""
    n = int(duration * SR)
    p = _t(n) / duration
    x = _band(rng.standard_normal(n), 300, 6000, 4) * p ** 3 + np.sin(2 * np.pi * (180 + 500 * p ** 2) * _t(n)) * p ** 4 * 0.4
    x[:int(0.01 * SR)] *= np.linspace(0, 1, int(0.01 * SR))
    x[-int(0.004 * SR):] *= np.linspace(1, 0, int(0.004 * SR))
    return np.stack([x, np.roll(x, int(0.003 * SR))], 1), duration


def clang(rng, root: float, weight: float = 1.0):
    """Two low thumps and a ring of metal: something very heavy being caught."""
    n = int(1.6 * SR)
    t = _t(n)
    x = np.zeros(n)
    for offset in (0.0, 0.13):
        k = int(offset * SR)
        tm = _t(n - k)
        x[k:] += np.sin(2 * np.pi * (75 - 30 * np.minimum(1.0, tm / 0.2)) * tm) * _decay(n - k, 0.001, 0.035) \
            + _band(rng.standard_normal(n - k), 500, 5000, 4) * _decay(n - k, 0.0005, 0.005) * 0.5
    ring = sum(np.sin(2 * np.pi * f * t) * _decay(n, 0.002, tau) * g for f, tau, g in ((412, 0.125, 0.25), (1033, 0.0875, 0.12), (1710, 0.0625, 0.07)))
    return _stereo(_tail(x + ring, 0.2)), 0.0


def glitch(rng, root: float, weight: float = 1.0):
    """A stuttered digital tear, for a frame that breaks up."""
    n = int(0.24 * SR)
    t = _t(n)
    gate = (np.floor(t * 55) % 2 == 0).astype(float)
    x = (np.sign(np.sin(2 * np.pi * 440 * t)) * 0.3 + _band(rng.standard_normal(n), 2000, 12000, 4)) * gate
    return _stereo(_tail(np.round(x * 6) / 6, 0.01)), 0.0


def heartbeat(rng, root: float, weight: float = 1.0):
    """One heartbeat: for the bars where the music drops out."""
    n = int(0.5 * SR)
    x = np.zeros(n)
    for offset, gain in ((0.0, 1.0), (0.17, 0.75)):
        k = int(offset * SR)
        x[k:] += np.sin(2 * np.pi * 52 * _t(n - k)) * _decay(n - k, 0.004, 0.015) * gain
    return _stereo(x), 0.0


def whip(rng, root: float, weight: float = 1.0):
    """A quick whip of air that peaks on a cut between cards."""
    n = int(0.3 * SR)
    t = _t(n)
    x = _band(rng.standard_normal(n), 600, 9000, 4) * np.sin(np.pi * t / 0.3) ** 2 * (0.6 + 0.4 * np.sin(2 * np.pi * (8 + 60 * t / 0.3) * t))
    return np.stack([x, np.roll(x, int(0.002 * SR))], 1), 0.15


def hum(rng, root: float, weight: float = 1.0, duration: float = 3.0):
    """Mains hum and a little hiss: an old screen or an empty room, as a bed under a shot."""
    n = int(duration * SR)
    t = _t(n)
    x = 0.6 * np.sin(2 * np.pi * 60 * t) + 0.35 * np.sin(2 * np.pi * 120 * t) + 0.12 * np.sin(2 * np.pi * 180 * t) \
        + 0.075 * _band(rng.standard_normal(n), 2000, 9000, 4)
    x[:int(0.15 * SR)] *= np.linspace(0, 1, int(0.15 * SR))
    return _stereo(_tail(x, 0.25)), 0.0


KIT = {"impact": impact, "sub": sub, "boom": boom, "riser": riser, "downlifter": downlifter, "whoosh": whoosh,
       "swell": swell, "tick": tick, "screen-on": screen_on, "static": static, "key": key, "shutter": shutter,
       "rocket": rocket, "blast": blast, "beep": beep, "reverse": reverse, "clang": clang, "glitch": glitch,
       "heartbeat": heartbeat, "whip": whip, "hum": hum}
STRETCHY = ("riser", "downlifter", "whoosh", "swell", "rocket", "reverse", "hum")  # these accept "dur"
# Loudness of each sound relative to the level asked for, so that "db" means roughly the same weight for all.
TRIM = {"impact": 0.0, "sub": 0.0, "boom": 0.0, "riser": -4.0, "downlifter": -2.0, "whoosh": -6.0, "swell": -6.0, "tick": -8.0,
        "screen-on": -2.0, "static": -4.0, "key": -10.0, "shutter": -6.0, "rocket": 0.0, "blast": 0.0, "beep": -10.0,
        "reverse": -3.0, "clang": 0.0, "glitch": -6.0, "heartbeat": 0.0, "whip": -5.0, "hum": -8.0}


def make(spec: dict, key_root: int | None = None):
    """Build one sound from a cut's ``sounds`` entry. Returns (stereo audio, lead seconds)."""
    kind = spec["kind"]
    seed = zlib.crc32(f"{spec.get('id', '')}:{kind}".encode())
    pitch = spec.get("pitch", key_root)
    kwargs = {"duration": float(spec["dur"])} if "dur" in spec and kind in STRETCHY else {}
    audio, lead = KIT[kind](np.random.default_rng(seed), root_hz(pitch), float(spec.get("weight", 1.0)), **kwargs)
    return _level(_stereo(audio), float(spec.get("db", -12.0)) + TRIM[kind]), lead
