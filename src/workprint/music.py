"""Music analysis: tempo, beats, bars, energy, sections, drops, accents and key.

The cut is planned on the grid this module produces. The methods are textbook
signal processing implemented with NumPy only:

* onset strength: half-wave rectified spectral flux of a log-compressed STFT
* tempo: autocorrelation of the onset strength with a log-normal tempo prior
* beats: dynamic programming over the onset strength (Ellis, "Beat Tracking by
  Dynamic Programming", 2007)
* bar phase: the beat position that carries the most low-frequency onset energy,
  assuming 4/4; the confidence is reported so the editor can override it
* sections and drops: changes in per-bar energy
* key: chroma correlated with the Krumhansl-Kessler key profiles
"""
from __future__ import annotations

import numpy as np

from . import ff

SR = 22050
HOP = 256
NFFT = 1024
FPS = SR / HOP
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _stft_mag(y: np.ndarray, nfft: int, hop: int) -> np.ndarray:
    pad = nfft // 2
    y = np.pad(y, (pad, pad), mode="reflect") if len(y) > pad else np.pad(y, (pad, pad))
    count = 1 + (len(y) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(count)[:, None]
    window = np.hanning(nfft).astype(np.float32)
    out = np.empty((count, nfft // 2 + 1), np.float32)
    for a in range(0, count, 4096):  # block-wise to bound memory
        out[a:a + 4096] = np.abs(np.fft.rfft(y[idx[a:a + 4096]] * window, axis=1))
    return out


def _smooth(x: np.ndarray, width: int) -> np.ndarray:
    width = max(1, int(width))
    return np.convolve(x, np.ones(width) / width, "same")


def onset_strength(mag: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Full-band and low-band (<150 Hz) onset strength, one value per STFT frame."""
    comp = np.log1p(10.0 * mag)
    flux = np.maximum(comp[1:] - comp[:-1], 0.0)
    flux = np.vstack([np.zeros((1, flux.shape[1]), np.float32), flux])
    low_bins = max(2, int(150 / (SR / NFFT)) + 1)

    def norm(env):
        env = np.maximum(env - _smooth(env, FPS * 0.5), 0.0)
        return env / (env.std() + 1e-9)

    return norm(flux.sum(1)), norm(flux[:, :low_bins].sum(1))


def _pick(env: np.ndarray, min_gap: float, k: float = 3.0, floor: float = 0.15) -> np.ndarray:
    """Frames where ``env`` peaks clearly above its own recent level."""
    from scipy.ndimage import maximum_filter1d, median_filter
    if not env.any():
        return np.array([], int)
    width = int(FPS) | 1
    middle = median_filter(env, size=width, mode="nearest")
    spread = median_filter(np.abs(env - middle), size=width, mode="nearest") + 1e-9
    reach = max(1, int(min_gap * FPS / 2))
    top = maximum_filter1d(env, size=2 * reach + 1, mode="nearest")
    return np.flatnonzero((env == top) & (env > middle + k * spread) & (env > floor * np.percentile(env, 99.5)))


def drum_hits(mag: np.ndarray) -> dict:
    """Times of drum hits by kind, measured from the track itself (no stem separation).

    A kick is a sudden rise at the bottom of the spectrum. A snare is a burst that is wide
    in frequency and short in time, strong in the mids and above them at once. A hat is
    the same kind of burst confined to the top. Sustained sound (notes, voices) is set
    aside first by comparing each point with its neighbours in time and in frequency.
    Clear, dry drums are found reliably; dense or heavily processed mixes less so.
    """
    from scipy.ndimage import median_filter
    comp = np.log1p(10.0 * mag)
    hz = SR / NFFT
    rise = lambda x: np.maximum(np.diff(x, axis=0, prepend=x[:1]), 0.0)
    kick = rise(comp[:, 1:int(130 / hz) + 1]).sum(1)
    short = comp * (median_filter(comp, size=(1, 17), mode="nearest") > median_filter(comp, size=(17, 1), mode="nearest"))
    flux = rise(short)
    band = lambda lo, hi: flux[:, int(lo / hz):int(hi / hz) + 1].sum(1)
    unit = lambda x: x / (np.percentile(x, 99.5) + 1e-9)
    snare = np.sqrt(unit(band(180, 2500)) * unit(band(2500, 7000)))
    hat = unit(band(7000, 11000))
    found = {"kick": _pick(kick, 0.14, k=5.0, floor=0.45), "snare": _pick(snare, 0.12, floor=0.3), "hat": _pick(hat, 0.06)}
    if len(found["kick"]):  # the click at the front of a kick is not a snare
        found["snare"] = np.array([f for f in found["snare"] if np.abs(found["kick"] - f).min() > 2], int)
    if len(found["snare"]):  # a snare also lights the top band: do not count it as a hat too
        found["hat"] = np.array([f for f in found["hat"] if np.abs(found["snare"] - f).min() > 2], int)
    return {name: [round(float(f) * HOP / SR, 3) for f in frames] for name, frames in found.items()}


def nearest_hit(music: dict, kind: str, t: float, within: float | None = None) -> float:
    """The drum hit of ``kind`` nearest to ``t`` (music time); ``t`` itself if there is none within ``within`` seconds."""
    hits = np.asarray((music.get("drums") or {}).get(kind, []), float)
    if not len(hits):
        return t
    best = float(hits[int(np.argmin(np.abs(hits - t)))])
    return best if within is None or abs(best - t) <= within else t


def estimate_tempo(env: np.ndarray, lo: float = 60.0, hi: float = 200.0) -> tuple[float, list[float]]:
    x = env - env.mean()
    n = int(2 ** np.ceil(np.log2(2 * len(x))))
    ac = np.fft.irfft(np.abs(np.fft.rfft(x, n)) ** 2)[: len(x)]
    ac /= ac[0] + 1e-9
    lags = np.arange(int(FPS * 60 / hi), int(FPS * 60 / lo) + 1)
    bpm = 60.0 * FPS / lags
    comb = ac[lags] + 0.5 * ac[np.minimum(2 * lags, len(ac) - 1)] + 0.25 * ac[np.minimum(4 * lags, len(ac) - 1)]
    prior = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.8) ** 2)
    score = comb * prior
    k = int(np.argmax(score))
    lag = float(lags[k])
    if 0 < k < len(lags) - 1:  # parabolic refinement between integer lags
        a, b, c = score[k - 1], score[k], score[k + 1]
        if (a - 2 * b + c) != 0:
            lag += 0.5 * (a - c) / (a - 2 * b + c)
    tempo = 60.0 * FPS / lag
    return float(tempo), [round(float(tempo) / 2, 2), round(float(tempo) * 2, 2)]


def track_beats(env: np.ndarray, tempo: float, tightness: float = 100.0) -> np.ndarray:
    """Beat positions as STFT frame indices (dynamic programming)."""
    period = FPS * 60.0 / tempo
    sigma = max(1.0, period / 32.0)
    kernel = np.exp(-0.5 * (np.arange(-int(3 * sigma), int(3 * sigma) + 1) / sigma) ** 2)
    local = np.convolve(env, kernel / kernel.sum(), "same")
    offsets = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
    cost = -tightness * np.log(-offsets / period) ** 2
    cum = np.zeros(len(local))
    back = np.full(len(local), -1, int)
    first = -offsets[-1]
    for i in range(len(local)):
        if i < first:
            cum[i] = local[i]
            continue
        prev = i + offsets
        ok = prev >= 0
        cand = cum[prev[ok]] + cost[ok]
        j = int(np.argmax(cand))
        cum[i] = local[i] + cand[j]
        back[i] = prev[ok][j]
    tail = max(0, len(cum) - int(round(period)))
    i = tail + int(np.argmax(cum[tail:]))
    beats = []
    while i >= 0:
        beats.append(i)
        i = back[i]
    return np.array(beats[::-1])


def _estimate_key(y: np.ndarray) -> dict:
    mag = _stft_mag(y, 8192, 4096).mean(0)
    freqs = np.fft.rfftfreq(8192, 1 / SR)
    keep = (freqs >= 65) & (freqs <= 2000)
    pitch = np.round(12 * np.log2(freqs[keep] / 440.0) + 69).astype(int) % 12
    chroma = np.bincount(pitch, weights=mag[keep] ** 2, minlength=12)
    chroma /= chroma.max() + 1e-12
    best = (-2.0, 0, "major")
    scores = []
    for root in range(12):
        for mode, profile in (("major", _MAJOR), ("minor", _MINOR)):
            r = float(np.corrcoef(np.roll(profile, root), chroma)[0, 1])
            scores.append(r)
            if r > best[0]:
                best = (r, root, mode)
    scores.sort()
    return {"name": f"{NOTES[best[1]]} {best[2]}", "root": best[1], "mode": best[2],
            "confidence": round(best[0] - scores[-2], 3)}


def _unit(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - lo) / (hi - lo + 1e-9), 0.0, 1.0)


def analyze(path) -> dict:
    y = ff.read_audio(path, SR, 1)[:, 0]
    duration = len(y) / SR
    mag = _stft_mag(y, NFFT, HOP)
    env, low_env = onset_strength(mag)
    tempo, alternates = estimate_tempo(env)
    frames = track_beats(env, tempo)
    beats = frames * HOP / SR

    # Bar phase: which of four beat positions carries the low-frequency accents.
    low_at = np.array([low_env[max(0, f - 2): f + 3].max() for f in frames])
    phase_score = [float(low_at[p::4].mean()) if len(low_at[p::4]) else 0.0 for p in range(4)]
    phase = int(np.argmax(phase_score))
    ranked = sorted(phase_score, reverse=True)
    phase_conf = (ranked[0] - ranked[1]) / (ranked[0] + 1e-9)

    # Per-beat energy, then per-bar.
    power = (mag ** 2)
    low_bins = max(2, int(150 / (SR / NFFT)) + 1)
    edges = np.append(frames, len(mag))
    e_db, l_db = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = power[a:max(b, a + 1)]
        e_db.append(10 * np.log10(seg.sum(1).mean() + 1e-9))
        l_db.append(10 * np.log10(seg[:, :low_bins].sum(1).mean() + 1e-9))
    e_unit, l_unit = _unit(np.array(e_db)), _unit(np.array(l_db))
    bar_idx = np.arange(phase, len(beats), 4)
    bars = beats[bar_idx]
    bar_e = np.array([e_unit[i:i + 4].mean() for i in bar_idx])
    bar_l = np.array([l_unit[i:i + 4].mean() for i in bar_idx])

    # Sections: boundaries where the energy picture changes between bars.
    sections, drops = [], []
    if len(bars) >= 2:
        novelty = np.abs(np.diff(bar_e)) + np.abs(np.diff(bar_l))
        threshold = novelty.mean() + 0.75 * novelty.std()
        cuts = [0]
        for k, v in enumerate(novelty, start=1):
            if v > threshold and k - cuts[-1] >= 2 and v >= novelty[max(0, k - 2): k + 1].max() - 1e-9:
                cuts.append(k)
        cuts.append(len(bars))
        for a, b in zip(cuts[:-1], cuts[1:]):
            energy = float(bar_e[a:b].mean())
            slope = float(np.polyfit(np.arange(b - a), bar_e[a:b], 1)[0]) if b - a >= 3 else 0.0
            label = "low" if energy < 0.33 else "mid" if energy < 0.66 else "high"
            if slope > 0.04:
                label += ", rising"
            end = float(bars[b]) if b < len(bars) else duration
            sections.append({"from": round(float(bars[a]), 3), "to": round(end, 3), "bars": [a + 1, b],
                             "energy": round(energy, 2), "label": label})
        for k in range(1, len(bars)):
            before = bar_e[max(0, k - 2):k].mean()
            jump = bar_l[k] - bar_l[k - 1]
            if jump >= 0.3 and bar_e[k] >= 0.6 and bar_e[k] - before >= 0.2:
                drops.append({"t": round(float(bars[k]), 3), "bar": k + 1, "strength": round(float(jump), 2)})
        drops.sort(key=lambda d: -d["strength"])

    # Accents: the strongest isolated onsets.
    radius = int(FPS * 0.1)
    peaks = [i for i in range(radius, len(env) - radius)
             if env[i] > 2.5 and env[i] == env[i - radius:i + radius + 1].max()]
    peaks.sort(key=lambda i: -env[i])
    top = float(env[peaks[0]]) if peaks else 1.0
    hits = sorted(({"t": round(i * HOP / SR, 3), "s": round(float(env[i]) / top, 2)} for i in peaks[:64]), key=lambda h: h["t"])

    return {
        "duration": round(duration, 3), "tempo": round(tempo, 2), "tempo_alternates": alternates, "meter": 4,
        "beats": [round(float(t), 3) for t in beats], "bar_phase": phase, "bar_phase_confidence": round(float(phase_conf), 2),
        "bars": [round(float(t), 3) for t in bars], "bar_energy": [round(float(v), 2) for v in bar_e],
        "bar_low": [round(float(v), 2) for v in bar_l], "sections": sections, "drops": drops[:6], "hits": hits,
        "key": _estimate_key(y), "drums": drum_hits(mag),
    }


# ---- grid helpers used by the planner, the checker and the revision commands --------------------

def grid(music: dict, subdivision: float = 1.0) -> np.ndarray:
    """Times on the beat grid. ``subdivision`` 2 gives eighth notes, 0.5 gives half notes."""
    beats = np.array(music["beats"])
    if len(beats) < 2:
        return beats
    if subdivision >= 1:
        steps = int(round(subdivision))
        parts = [beats[:-1] + (beats[1:] - beats[:-1]) * k / steps for k in range(steps)]
        return np.sort(np.concatenate(parts + [beats[-1:]]))
    every = int(round(1 / subdivision))
    phase = music.get("bar_phase", 0) % every
    return beats[phase::every]


def snap(music: dict, t: float, subdivision: float = 1.0) -> float:
    """Nearest grid time to ``t`` (music time)."""
    g = grid(music, subdivision)
    return float(g[int(np.argmin(np.abs(g - t)))]) if len(g) else t


def bar_time(music: dict, bar: float) -> float:
    """Music time of a 1-based bar number; fractional bars interpolate (2.5 = middle of bar 2)."""
    bars = music["bars"]
    if not bars:
        return 0.0
    i = int(np.floor(bar)) - 1
    step = float(np.median(np.diff(bars))) if len(bars) > 1 else 0.0
    if i < 0:
        return bars[0] + (bar - 1) * step
    if i >= len(bars) - 1:
        return bars[-1] + (bar - len(bars)) * step
    return bars[i] + (bars[i + 1] - bars[i]) * (bar - 1 - i)
