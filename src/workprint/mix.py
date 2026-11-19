"""The sound mix: music bed, voice, clip sound and designed sounds, mastered to a loudness target.

Mixing happens in NumPy at 48 kHz stereo. Loudness is measured with ffmpeg's EBU R128
meter; a look-ahead limiter holds the peak ceiling. The mix is cached by its inputs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from . import ff, sound
from .manifest import speed_pair, timeline

MIX_REV = 1
SR = sound.SR


def _place(bus: np.ndarray, audio: np.ndarray, at: float) -> None:
    start = int(round(at * SR))
    if start < 0:
        audio, start = audio[-start:], 0
    n = min(len(audio), len(bus) - start)
    if n > 0:
        bus[start:start + n] += audio[:n]


def _fades(audio: np.ndarray, fade_in: float, fade_out: float) -> np.ndarray:
    audio = audio.copy()
    for seconds, tail in ((fade_in, False), (fade_out, True)):
        k = min(len(audio), int(seconds * SR))
        if k > 1:
            ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
            if tail:
                audio[-k:] *= ramp[::-1, None]
            else:
                audio[:k] *= ramp[:, None]
    return audio


def limit(x: np.ndarray, ceiling_db: float = -1.0) -> np.ndarray:
    """Look-ahead peak limiter: gain never rises above what keeps every sample under the ceiling."""
    ceiling = sound.db(ceiling_db - 0.3)  # margin for inter-sample peaks
    need = np.minimum(1.0, ceiling / np.maximum(np.abs(x).max(1), 1e-9))
    if need.min() >= 1.0:
        return x
    look, release = int(0.005 * SR), int(0.08 * SR)
    gain = minimum_filter1d(need, size=2 * look + 1, mode="nearest")
    gain = minimum_filter1d(gain, size=release, mode="nearest", origin=(release - 1) // 2)  # hold after a peak, then let go
    gain = uniform_filter1d(gain, size=look, mode="nearest")
    return x * np.minimum(gain, need)[:, None]


def _spec(project, cut: dict) -> dict:
    """Everything that affects the mix, for the cache key."""
    fps = cut["format"]["fps"]
    nat = [[s["cut"]["src"], s["cut"]["in"], s["f0"], s["f1"], s["cut"]["nat"]] for s in timeline(cut)
           if s["cut"].get("nat") is not None and "src" in s["cut"]]
    music_sig = project.data["music"]["sig"] if (cut.get("music") and project.data.get("music")) else None
    key = (project.music() or {}).get("key", {}).get("root")
    return {"rev": MIX_REV, "duration": cut["duration"], "fps": fps, "music": cut.get("music"), "music_sig": music_sig,
            "sounds": cut.get("sounds"), "voice": cut.get("voice"), "nat": nat, "audio": cut.get("audio"), "key": key}


def build(project, cut: dict) -> dict | None:
    """Build (or reuse) the mix for a cut. Returns {"path", "lufs", "true_peak", "lra"} or None if silent."""
    spec = _spec(project, cut)
    if not (spec["music"] or spec["sounds"] or spec["voice"] or spec["nat"]):
        return None
    folder = project.cache_dir / "mix"
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:20]
    path, meta = folder / f"{key}.wav", folder / f"{key}.json"
    if path.exists() and meta.exists():
        return {"path": path, **json.loads(meta.read_text())}

    n = int(round(cut["duration"] * SR))
    settings = cut.get("audio") or {}
    music_bus, voice_bus, other = np.zeros((n, 2)), np.zeros((n, 2)), np.zeros((n, 2))

    music = cut.get("music")
    if music and project.music_path():
        audio = ff.read_audio(project.music_path(), SR, 2, music.get("in", 0.0), cut["duration"]).astype(np.float64)
        audio = _fades(audio, music.get("fade_in", 0.0), music.get("fade_out", 0.0))
        gain = np.full(len(audio), float(music.get("gain_db", 0.0)))
        points = music.get("automation")  # [[time, dB], ...] added on top of gain_db
        if points:
            times, values = zip(*sorted(points))
            gain += np.interp(np.arange(len(audio)) / SR, times, values)
        _place(music_bus, audio * (10.0 ** (gain / 20.0))[:, None], 0.0)

    for item in cut.get("voice") or []:
        file = Path(item["file"])
        file = file if file.is_absolute() else project.root / file
        audio = ff.read_audio(file, SR, 1, item.get("in", 0.0), item.get("dur")).astype(np.float64)
        audio = _fades(np.repeat(audio, 2, axis=1), 0.02, 0.05) * sound.db(item.get("gain_db", 0.0))
        _place(voice_bus, audio, item["at"])
    if voice_bus.any():  # duck the music under speech
        envelope = np.sqrt(uniform_filter1d((voice_bus.mean(1)) ** 2, size=int(0.25 * SR)))
        active = np.clip((20 * np.log10(envelope + 1e-9) + 50.0) / 14.0, 0.0, 1.0)
        music_bus *= (10.0 ** (float(settings.get("duck_db", -6.0)) * active / 20.0))[:, None]

    fps = cut["format"]["fps"]
    for slot in timeline(cut):  # the clips' own sound, where asked for
        entry = slot["cut"]
        if entry.get("nat") is None or "src" not in entry or speed_pair(entry) != (1.0, 1.0):
            continue
        source = project.source(entry["src"])
        if not source.get("has_audio"):
            continue
        audio = ff.read_audio(project.path_of(source), SR, 2, entry["in"], (slot["f1"] - slot["f0"]) / fps).astype(np.float64)
        _place(other, _fades(audio, 0.012, 0.012) * sound.db(entry["nat"]), slot["f0"] / fps)

    key_root = spec["key"]
    for item in cut.get("sounds") or []:
        if "file" in item:
            file = Path(item["file"])
            audio = ff.read_audio(file if file.is_absolute() else project.root / file, SR, 2).astype(np.float64)
            audio, lead = audio * sound.db(item.get("db", 0.0)), 0.0
        else:
            audio, lead = sound.make(item, key_root)
        _place(other, audio, item["at"] - lead)

    mixed = music_bus + voice_bus + other
    target = settings.get("target_lufs", -14.0)
    probe = folder / f"{key}.probe.wav"
    if target is not None:
        ff.write_wav(probe, mixed / max(1.0, np.abs(mixed).max()), SR)
        measured = ff.loudness(probe)["lufs"]
        probe.unlink(missing_ok=True)
        if measured is not None and measured > -70:
            scale = 1.0 / max(1.0, np.abs(mixed).max())
            mixed = mixed * scale * sound.db(min(18.0, target - measured))
    mixed = limit(mixed, float(settings.get("ceiling_db", -1.0)))
    ff.write_wav(path, mixed, SR)
    result = ff.loudness(path)
    meta.write_text(json.dumps(result))
    return {"path": path, **result}
