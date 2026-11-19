"""First assembly: turn an editorial structure into a cut on the musical grid.

The editor (Claude, working from the brief, the shot log and the music analysis)
writes a *structure*: sections of the film, how hard each one should hit, how often
it cuts, which shots are pinned to which moments. This module does the mechanical
part: lays cut points on the beat grid, fills each slot with the best-fitting logged
shot, chooses an in-point inside that shot, and records why. The result is a normal
cut that the editor then reviews and revises; it is a starting point, not a verdict.

    {
      "duration": 40, "music_in": 137.8,
      "sections": [
        {"name": "quiet", "from": 0, "to": 13.7, "energy": 0.2, "every": 8, "tags": ["wide"], "move": "push"},
        {"name": "build", "from": 13.7, "to": 27.4, "energy": 0.6, "every": [4, 2]},
        {"name": "drop",  "from": 27.4, "to": 37.0, "energy": 1.0, "every": 1}
      ],
      "pins": [{"at": 27.4, "shot": "A004-07"}],
      "end_card": {"dur": 3.0, "text": "TITLE"}
    }

``every`` is the number of beats between cuts (4 = one bar in 4/4, 0.5 = eighth notes);
a list splits the section into equal parts with accelerating or relaxing rates.

A section with ``"on": "kick"`` (or ``snare``, ``hat``) keeps the ``every`` grid but moves
each cut onto the nearest drum hit of that kind within a quarter of a beat, so cuts sit
on the transient itself and not on the idealised grid.

A structure may also place a voice (``"voice": [{"src": "V01", "at": 4.0}]``). A section
with ``"follow": "voice"`` then cuts on the breath: a cut just ahead of each phrase (on
the beat when one is within a tenth of a second), no cut while someone is speaking,
and the ``every`` grid in the gaps between phrases.
"""
from __future__ import annotations

import numpy as np

from . import music as music_mod
from .manifest import new_cut, normalize


def _grid_times(analysis: dict, every: float, anchor: float) -> np.ndarray:
    """Music times of a cutting grid with ``every`` beats between cuts, counted from the grid point nearest ``anchor``.

    Anchoring at the section's start means "every 8 beats" gives two-bar phrases that begin where the
    section begins, whatever bar of the track that happens to be.
    """
    sub = next((s for s in (1, 2, 3, 4, 8) if abs(every * s - round(every * s)) < 1e-6), 8)
    g = music_mod.grid(analysis, sub)
    step = max(1, int(round(every * sub)))
    start = int(np.argmin(np.abs(g - anchor))) % step
    return g[start::step]


def cut_points(analysis: dict | None, music_in: float, sections: list[dict], duration: float, fps: float,
               phrases: list[list[float]] | None = None) -> list[tuple[float, dict]]:
    """Film times of every cut, each with the section it belongs to."""
    points: dict[int, tuple[float, dict]] = {}
    beats = np.asarray((analysis or {}).get("beats", []), float) - music_in
    for section in sections:
        a, b = float(section["from"]), float(section["to"])
        rates = section.get("every", 4)
        rates = rates if isinstance(rates, list) else [rates]
        span = (b - a) / len(rates)
        times = [a]
        for k, rate in enumerate(rates):
            lo, hi = a + k * span, a + (k + 1) * span
            if analysis and len(analysis.get("beats", [])) > 4:
                g = _grid_times(analysis, float(rate), lo + music_in) - music_in
            else:  # no music: an even grid at the requested rate, treating a beat as half a second
                g = np.arange(a, b, max(2 / fps, float(rate) * 0.5))
            first = lo + 1.5 / fps if k == 0 else lo - 0.5 / fps  # later parts begin with a cut of their own
            times += [float(t) for t in g if first < t < hi - 1.5 / fps]
        if section.get("on") and analysis and (analysis.get("drums") or {}).get(section["on"]):
            reach = 0.25 * float(np.median(np.diff(analysis["beats"]))) if len(analysis.get("beats", [])) > 1 else 0.12
            times = sorted({times[0], *(music_mod.nearest_hit(analysis, section["on"], t + music_in, reach) - music_in
                                         for t in times[1:])})
        if section.get("follow") == "voice" and phrases:
            times = _follow_voice(times, a, b, phrases, beats, float(section.get("lead", 2.0 / fps)), fps)
        for t in times:
            if 0 <= t < duration - 1.5 / fps:
                points.setdefault(int(round(t * fps)), (t, section))
    return [points[f] for f in sorted(points)]


def _follow_voice(times: list[float], a: float, b: float, phrases: list[list[float]], beats: np.ndarray, lead: float,
                  fps: float) -> list[float]:
    """Cut on the breath: a cut just ahead of each phrase, none while someone is speaking, the grid kept in the gaps."""
    spoken = [(s, e) for s, e in phrases if a + 1.5 / fps < s - lead < b - 1.5 / fps]
    anchors = []
    for s, _ in spoken:
        t = s - lead
        if len(beats):  # take the beat instead when one is close enough to pass for it
            near = float(beats[int(np.argmin(np.abs(beats - t)))])
            if abs(near - t) <= 0.1 and near < s:
                t = near
        anchors.append(t)
    gap = max(0.4, 6.0 / fps)
    kept = [t for t in times if t == a or (all(abs(t - x) >= gap for x in anchors)
                                           and not any(s - lead - 1e-6 < t < e for s, e in phrases))]
    return sorted(set(kept + anchors))


def _usable(shot: dict) -> bool:
    return not shot.get("black") and shot.get("rating") != 0


def _in_point(shot: dict, need: float, energy: float, used_spans: list[tuple[float, float]]) -> float:
    """Pick where in the shot to start: around its motion peak when the film is loud, its calm stretch when quiet."""
    margin = min(0.08, max(0.0, (shot["dur"] - need) / 2))
    lo, hi = shot["start"] + margin, shot["end"] - margin - need
    want = shot["start"] + (shot.get("peak", 0.0) - need * 0.35 if energy >= 0.6 else shot.get("calm", 0.0))
    t = min(max(want, lo), max(lo, hi))
    for a, b in used_spans:  # avoid showing the same moment twice when a shot is reused
        if min(t + need, b) - max(t, a) > 0.1:
            later = b + 0.05
            t = later if later <= hi else max(lo, min(hi, a - need - 0.05))
    return round(t, 3)


def draft(project, structure: dict) -> dict:
    """Build a cut from a structure. Deterministic for the same inputs."""
    fmt = project.format
    fps = fmt["fps"]
    analysis = project.music()
    music_in = float(structure.get("music_in", 0.0))
    card = structure.get("end_card")
    duration = float(structure["duration"])
    picture_end = duration - (float(card["dur"]) if card else 0.0)
    shots = [s for s in project.shots() if _usable(s)]
    if not shots:
        raise ValueError("the shot log has no usable shots: run `workprint ingest` first")
    motions = np.array([s["motion"] for s in shots])
    lo, hi = np.percentile(motions, 5), np.percentile(motions, 95)

    def liveliness(shot):
        return float(np.clip((shot["motion"] - lo) / (hi - lo + 1e-9), 0, 1))

    pins = {int(round(float(p["at"]) * fps)): p for p in structure.get("pins", [])}
    phrases = None
    if structure.get("voice") and any(s.get("follow") == "voice" for s in structure["sections"]):
        from .voice import placed_phrases
        phrases = placed_phrases(project, {"voice": structure["voice"]})
    points = cut_points(analysis, music_in, structure["sections"], picture_end, fps, phrases)
    frames = {int(round(t * fps)) for t, _ in points}
    for f, pin in pins.items():  # a pin always gets its own cut point
        if f not in frames:
            section = next((s for s in structure["sections"] if s["from"] <= f / fps < s["to"]), structure["sections"][-1])
            points.append((f / fps, section))
    points.sort(key=lambda p: p[0])

    cut = new_cut(fmt, duration, structure.get("title", project.data.get("name", "")))
    cut["music"] = {"in": music_in, "gain_db": 0.0, "fade_in": 0.0, "fade_out": structure.get("music_fade_out", 1.5)} if project.data.get("music") else None
    for key in ("look", "titles", "sounds", "audio", "voice"):
        if key in structure:
            cut[key] = structure[key]
    cut["sections"] = [{k: s[k] for k in ("name", "from", "to", "energy", "note") if k in s} for s in structure["sections"]]

    by_id = {s["id"]: s for s in shots}
    # Pinned shots count as used from the start, so the planner does not spend them somewhere else first.
    uses: dict[str, list[tuple[float, float]]] = {p["shot"]: [(-1.0, -1.0)] for p in structure.get("pins", [])}
    previous = None
    for k, (t, section) in enumerate(points):
        end = points[k + 1][0] if k + 1 < len(points) else picture_end
        need = end - t
        energy = float(section.get("energy", 0.5))
        pin = pins.get(int(round(t * fps)))
        if pin:
            shot, why = by_id[pin["shot"]], "pinned by the editor"
        else:
            best, why = None, ""
            for cand in shots:
                if cand["dur"] < need + 0.04 or set(cand.get("tags", [])) & set(section.get("avoid", [])):
                    continue
                rating = cand["rating"] if cand.get("rating") is not None else 2.5
                match = 1.0 - abs(liveliness(cand) - energy)
                tags = len(set(cand.get("tags", [])) & set(section.get("tags", [])))
                score = match + 0.9 * rating / 5.0 + 0.35 * tags - 1.5 * len(uses.get(cand["id"], []))
                if previous and cand["src"] == previous["src"]:
                    score -= 0.25
                if previous and cand["id"] == previous["id"]:
                    score -= 1.0
                if best is None or score > best[0] + 1e-9:
                    best = (score, cand)
                    why = f"energy {energy:.1f} vs shot liveliness {liveliness(cand):.2f}, rated {rating}" + (f", {tags} tag match" if tags else "")
            if best is None:  # nothing long enough: take the longest shot and let validation flag it
                best = (0.0, max(shots, key=lambda s: s["dur"]))
                why = "no logged shot is long enough for this slot"
            shot = best[1]
        start = float(pin["in"]) if pin and "in" in pin else _in_point(shot, need, energy, uses.get(shot["id"], []))
        uses.setdefault(shot["id"], []).append((start, start + need))
        entry = {"id": f"c{k + 1:03d}", "at": round(t, 5), "src": shot["src"], "in": start, "shot": shot["id"],
                 "note": f"{section.get('name', '')}: {why}".strip(": ")}
        if section.get("move") == "push" and need >= 1.5:
            entry["move"] = {"zoom": [1.0, 1.05]}
        cut["cuts"].append(entry)
        previous = shot
    if card:
        cut["cuts"].append({"id": "card", "at": round(picture_end, 5), "card": {"bg": card.get("bg", "#000000")},
                            "note": "end card"})
        if card.get("text"):
            cut["titles"].append({"id": "t_end", "at": round(picture_end + 0.1, 3), "dur": round(float(card["dur"]) - 0.1, 3),
                                  "text": card["text"], "style": card.get("style", {}), "fade": [0.0, 0.4]})
    return normalize(cut)
