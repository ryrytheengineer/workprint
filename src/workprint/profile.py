"""Style profiles: measurable habits extracted from reference films.

A profile is not a model of anyone's taste. It is a set of numbers measured from
films the editor likes (how long shots run, how the cutting rate changes over the
film, how often cuts land on the beat, how loud and how dynamic the sound is) plus
an editable ``preferences`` block derived from them, which the planner uses for
defaults. The editor reads it, corrects it, and it becomes more theirs over time.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import __version__, ff, music as music_mod, shots


def measure(path) -> dict:
    """Measure one reference film."""
    path = Path(path)
    info = ff.probe(path)
    fps = info["fps"]
    sig = shots.frame_signals(path, {"fps": fps, "matrix": ff.color_matrix(info)})
    count = len(sig["hist"])
    duration = count / fps
    cuts = shots.find_cuts(sig["hist"], sig["diff"], fps, min_len=2.5 / fps)
    bounds = np.array([0] + cuts + [count]) / fps
    lengths = np.diff(bounds)
    thirds = [int(((bounds[1:-1] >= duration * k / 3) & (bounds[1:-1] < duration * (k + 1) / 3)).sum()) for k in range(3)]
    dark = (sig["luma"] < 0.02) & (sig["peak"] < 0.08)
    dips = int(((~dark[:-1]) & dark[1:]).sum())
    out = {
        "file": path.name, "duration": round(duration, 2), "size": [info["width"], info["height"]], "fps": fps,
        "shots": int(len(lengths)), "cuts_per_minute": round(len(cuts) / duration * 60, 1),
        "shot_length": {"mean": round(float(lengths.mean()), 2), "median": round(float(np.median(lengths)), 2),
                        "p10": round(float(np.percentile(lengths, 10)), 2), "p90": round(float(np.percentile(lengths, 90)), 2),
                        "shortest": round(float(lengths.min()), 2), "longest": round(float(lengths.max()), 2)},
        "cuts_by_third": thirds, "dips_to_black": dips,
        "picture": {"luma": round(float(sig["luma"].mean()), 3), "contrast": round(float(sig["contrast"].mean()), 3),
                    "saturation": round(float(sig["sat"].mean()), 3)},
    }
    # Letterbox: rows that stay black through the film.
    probe_times = [duration * k / 6 for k in range(1, 6)]
    rows = np.mean([ff.grab_frame(path, t, 320).mean(axis=(1, 2)) for t in probe_times], axis=0)
    bar = 0
    while bar < len(rows) // 3 and rows[bar] < 6 and rows[-1 - bar] < 6:
        bar += 1
    visible = len(rows) - 2 * bar
    out["letterbox"] = round(320 / visible, 2) if bar >= 2 and visible > 0 else 0.0
    if info.get("has_audio"):
        analysis = music_mod.analyze(path)
        loud = ff.loudness(path)
        beats, bars = np.array(analysis["beats"]), np.array(analysis["bars"])
        tol = max(1 / fps, 0.045)
        times = bounds[1:-1]
        on_beat = float(np.mean([np.abs(beats - t).min() <= tol for t in times])) if len(times) and len(beats) else 0.0
        on_bar = float(np.mean([np.abs(bars - t).min() <= tol for t in times])) if len(times) and len(bars) else 0.0
        # Shot length where the music is quiet, medium and loud.
        tiers: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
        energy = np.array(analysis["bar_energy"])
        for a, length in zip(bounds[:-1], lengths):
            if len(bars):
                e = energy[max(0, int(np.searchsorted(bars, a, side="right")) - 1)]
                tiers["low" if e < 0.34 else "mid" if e < 0.67 else "high"].append(length)
        beat = 60.0 / analysis["tempo"]
        out["music"] = {"tempo": analysis["tempo"], "key": analysis["key"]["name"], "cuts_on_beat": round(on_beat, 2),
                        "cuts_on_bar": round(on_bar, 2), "lufs": loud["lufs"], "lra": loud["lra"], "true_peak": loud["true_peak"],
                        "beats_per_cut": {k: round(float(np.median(v)) / beat, 2) for k, v in tiers.items() if v}}
    return out


def _round_to_grid(beats: float) -> float:
    """Nearest musically sensible cutting rate."""
    options = [0.25, 0.5, 1, 2, 4, 8, 16]
    return min(options, key=lambda o: abs(np.log2(o) - np.log2(max(beats, 0.125))))


def build(paths: list) -> dict:
    """Measure one or more references and derive editable preferences."""
    measured = [measure(p) for p in paths]
    every = {}
    for tier in ("low", "mid", "high"):
        values = [m["music"]["beats_per_cut"][tier] for m in measured if m.get("music") and tier in m["music"]["beats_per_cut"]]
        if values:
            every[tier] = _round_to_grid(float(np.median(values)))
    boxes = [m["letterbox"] for m in measured if m["letterbox"]]
    loud = [m["music"]["lufs"] for m in measured if m.get("music") and m["music"]["lufs"] is not None]
    preferences = {
        "every": every,
        "letterbox": round(float(np.median(boxes)), 2) if len(boxes) > len(measured) / 2 else 0.0,
        "target_lufs": round(float(np.median(loud)), 1) if loud else -14.0,
        "notes": "Edit freely. `workprint draft --profile` uses `every` (beats between cuts by music energy) "
                 "when a section does not set its own, and `letterbox` when the structure sets no look.",
    }
    return {"workprint": __version__, "measured": measured, "preferences": preferences}


def describe(profile: dict) -> str:
    lines = []
    for m in profile["measured"]:
        s = m["shot_length"]
        lines.append(f"{m['file']}: {m['duration']}s, {m['shots']} shots, {m['cuts_per_minute']} cuts/min, "
                     f"shot length median {s['median']}s (10% under {s['p10']}s, 10% over {s['p90']}s)")
        lines.append(f"  cuts by third of the film: {m['cuts_by_third']}; dips to black: {m['dips_to_black']}; "
                     f"letterbox: {m['letterbox'] or 'none'}; luma {m['picture']['luma']}, saturation {m['picture']['saturation']}")
        if m.get("music"):
            a = m["music"]
            lines.append(f"  music {a['tempo']} BPM, {a['key']}; {a['cuts_on_beat'] * 100:.0f}% of cuts on a beat, "
                         f"{a['cuts_on_bar'] * 100:.0f}% on a bar line; {a['lufs']} LUFS, range {a['lra']} LU; "
                         f"beats per cut by energy: {a['beats_per_cut']}")
    lines.append(f"preferences: {profile['preferences']['every']} beats per cut, letterbox "
                 f"{profile['preferences']['letterbox'] or 'none'}, target {profile['preferences']['target_lufs']} LUFS")
    return "\n".join(lines)


def apply(structure: dict, profile: dict) -> dict:
    """Fill a structure's unset choices from a profile's preferences."""
    prefs = profile.get("preferences", {})
    for section in structure.get("sections", []):
        if "every" not in section:
            e = float(section.get("energy", 0.5))
            tier = "low" if e < 0.34 else "mid" if e < 0.67 else "high"
            if tier in prefs.get("every", {}):
                section["every"] = prefs["every"][tier]
    if "look" not in structure and prefs.get("letterbox"):
        structure["look"] = {"letterbox": prefs["letterbox"]}
    if "audio" not in structure and prefs.get("target_lufs") is not None:
        structure["audio"] = {"target_lufs": prefs["target_lufs"]}
    return structure
