"""The cut: Workprint's persistent, human-readable edit manifest.

A cut is a JSON document. Picture is a list of *slots*: each cut entry names the
timeline time at which it starts (``at``) and what fills the frame until the next
entry starts. Cut points are therefore anchored to the timeline (and so to the
music), not to the lengths of the clips, which is how a music-driven edit is
actually thought about: replacing a shot never moves a cut, and moving a cut
changes exactly the two slots on either side of it.

    {
      "format":   {"width": 1920, "height": 1080, "fps": 24},
      "duration": 38.0,
      "music":    {"in": 12.4, "gain_db": 0, "fade_in": 0, "fade_out": 1.5},
      "look":     {"preset": "steel", "grain": 0.03, "vignette": 0.2, "letterbox": 2.39},
      "cuts":     [{"id": "c001", "at": 0.0, "src": "A003", "in": 14.2, "note": "opening wide"}, ...],
      "titles":   [{"id": "t01", "at": 35.2, "dur": 2.5, "text": "NEVER THE SAME"}],
      "sounds":   [{"id": "s01", "at": 22.0, "kind": "impact", "db": -10}]
    }

Optional per-cut fields: ``speed`` (number or [from, to]), ``move`` (zoom/x/y ramps),
``fit``, ``focus``, ``grade``, ``fx``, ``t`` (transition into the slot), ``freeze``,
``nat`` (dB of the clip's own sound), ``shot`` and ``note`` (for humans), or ``card``
instead of ``src`` for a plain colour card.

Two more lists carry speech: ``voice`` places a recording on the timeline
(``{"id": "v01", "src": "V01", "at": 4.0, "in": 12.5, "dur": 6.2, "gain_db": 0}``) and
``captions`` holds the words drawn over the picture (see ``captions.py``).
"""
from __future__ import annotations

import copy
from pathlib import Path

from . import __version__
from .project import write_json

LISTS = ("sections", "cuts", "titles", "sounds", "voice", "captions", "hud")
SOLO_FRAMES = 12  # slots at least this long are cached as their own render chunk
SOUND_KINDS = ("impact", "sub", "riser", "downlifter", "whoosh", "swell", "tick", "boom", "screen-on", "static", "key", "shutter",
               "rocket", "blast", "beep", "reverse", "clang", "glitch", "heartbeat", "whip", "hum")
FX_NAMES = ("punch", "rgbsplit", "invert", "xray", "xray-scan", "xray-pulse", "xray-flicker", "mono", "shake", "details")
RAMPS = {"linear": 0.5, "inout": 0.5, "in": 1.0 / 3.0, "out": 2.0 / 3.0}  # mean of each easing curve
INTERP = ("nearest", "blend", "flow")
TRANSITIONS = ("cut", "dissolve", "dip", "flash", "matte")
OVERLAPS = ("dissolve", "matte")  # transitions during which the outgoing shot keeps running


def frame_of(t: float, fps: float) -> int:
    return int(round(t * fps + 1e-9))


def new_cut(fmt: dict, duration: float, title: str = "") -> dict:
    return {"workprint": __version__, "title": title, "format": dict(fmt), "duration": duration,
            "music": None, "look": {}, "sections": [], "cuts": [], "titles": [], "sounds": []}


def dump(cut: dict, path: Path) -> None:
    write_json(Path(path), cut, compact_lists=LISTS)


def next_id(cut: dict, key: str, prefix: str) -> str:
    """A fresh id, one above the highest in use, so the id of a removed entry is not handed out again."""
    used = {item["id"] for item in cut.get(key, []) if item.get("id")}
    numbers = [int(i[len(prefix):]) for i in used if i.startswith(prefix) and i[len(prefix):].isdigit()]
    n = max(numbers, default=0) + 1
    while f"{prefix}{n:03d}" in used:
        n += 1
    return f"{prefix}{n:03d}"


def normalize(cut: dict) -> dict:
    """Sort cuts by time, snap times to the frame grid, and give every entry an id."""
    fps = cut["format"]["fps"]
    cut["duration"] = round(frame_of(cut["duration"], fps) / fps, 5)
    for item in cut.get("cuts", []):
        item["at"] = round(frame_of(item["at"], fps) / fps, 5)
    cut["cuts"] = sorted(cut.get("cuts", []), key=lambda c: c["at"])
    if cut.get("captions"):
        cut["captions"] = sorted(cut["captions"], key=lambda c: c.get("at", 0.0))
    for key, prefix in (("cuts", "c"), ("titles", "t"), ("sounds", "s"), ("voice", "v"), ("captions", "k"), ("hud", "h")):
        if key in ("voice", "captions", "hud") and not cut.get(key):
            continue
        cut.setdefault(key, [])
        for item in cut[key]:
            if not item.get("id"):
                item["id"] = next_id(cut, key, prefix)
    return cut


def timeline(cut: dict) -> list[dict]:
    """Slots in frames: [{"cut": entry, "f0": first frame, "f1": end frame (exclusive)}]."""
    fps = cut["format"]["fps"]
    total = frame_of(cut["duration"], fps)
    cuts = sorted(cut["cuts"], key=lambda c: c["at"])
    out = []
    for i, entry in enumerate(cuts):
        f0 = frame_of(entry["at"], fps)
        f1 = frame_of(cuts[i + 1]["at"], fps) if i + 1 < len(cuts) else total
        out.append({"cut": entry, "f0": f0, "f1": f1})
    return out


def speed_pair(entry: dict) -> tuple[float, float]:
    speed = entry.get("speed", 1.0)
    if isinstance(speed, (list, tuple)):
        return float(speed[0]), float(speed[1])
    return float(speed), float(speed)


def source_span(entry: dict, frames: int, fps: float) -> tuple[float, float]:
    """Source time range (seconds) a slot of ``frames`` frames reads."""
    if entry.get("freeze"):
        return entry["in"], entry["in"]
    s0, s1 = speed_pair(entry)
    if entry.get("ramp", "linear") not in ("linear", "inout") and entry.get("ramp") in RAMPS:
        return entry["in"], entry["in"] + (frames / fps) * (s0 + (s1 - s0) * RAMPS[entry["ramp"]])
    return entry["in"], entry["in"] + (frames / fps) * (s0 + s1) / 2.0


def alternate_frames(frames: int, start: int = 0, end: int | None = None, every: int = 2, pattern: list | None = None) -> set[int]:
    """Local frames on the "other" side of a flicker: runs of ``every`` frames (or the run lengths in ``pattern``), main first."""
    runs = [max(1, int(r)) for r in (pattern or [every])]
    end = frames if end is None else min(frames, int(end))
    out, k, i, other = set(), max(0, int(start)), 0, False
    while k < end:
        run = runs[i % len(runs)]
        if other:
            out.update(range(k, min(end, k + run)))
        k, i, other = k + run, i + 1, not other
    return out


def intercut_frames(entry: dict, frames: int, fps: float) -> set[int]:
    spec = entry.get("intercut") or {}
    if not spec:
        return set()
    end = int(round(float(spec["to"]) * fps)) if spec.get("to") is not None else None
    return alternate_frames(frames, int(round(float(spec.get("from", 0.0)) * fps)), end, int(spec.get("every", 2)), spec.get("pattern"))


def transition_of(entry: dict) -> dict:
    t = entry.get("t", "cut")
    if isinstance(t, str):
        t = {"type": t}
    out = {"type": t.get("type", "cut"), "frames": int(t.get("frames", 0 if t.get("type", "cut") == "cut" else 8))}
    if "color" in t:
        out["color"] = t["color"]
    if "style" in t:  # matte: through (default), hold, pin, lead, spin-out, spin-in, fly-out or fly-in
        out["style"] = t["style"]
    if "flash" in t:  # matte: frames of flash as the new shot's own background arrives after the subject
        out["flash"] = int(t["flash"])
    if "spin" in t:  # spin-out / spin-in: +1 or -1, which way it turns and which side it flies to
        out["spin"] = float(t["spin"])
    return out


def find(cut: dict, key: str, item_id: str) -> dict:
    for item in cut.get(key, []):
        if item.get("id") == item_id:
            return item
    raise KeyError(f"no {key[:-1]} with id {item_id!r}")


def detail_problems(fx: dict, frames: int) -> list[str]:
    """What is wrong with a details flash: every spot needs a box inside the frame and a frame inside the slot."""
    from .look import DETAIL_KEYS, DETAIL_MODES
    errors = []
    spots = fx.get("spots") if isinstance(fx, dict) else None
    if not spots:
        return ["details needs spots: [{frame, box: [x, y, w, h]}]"]
    for k, spot in enumerate(spots):
        box = spot.get("box")
        if not (isinstance(box, (list, tuple)) and len(box) == 4 and box[2] > 0 and box[3] > 0
                and 0 <= box[0] < 1 and 0 <= box[1] < 1):
            errors.append(f"details spot {k}: box must be [x, y, w, h] as fractions of the frame")
        if not 0 <= int(spot.get("frame", 0)) < frames:
            errors.append(f"details spot {k}: frame {spot.get('frame', 0)} is outside the slot (0-{frames - 1})")
        if spot.get("mode", "fill") not in DETAIL_MODES:
            errors.append(f"details spot {k}: unknown mode {spot.get('mode')!r} (known: {', '.join(DETAIL_MODES)})")
        if spot.get("key", "auto") not in DETAIL_KEYS:
            errors.append(f"details spot {k}: unknown key {spot.get('key')!r} (known: {', '.join(DETAIL_KEYS)})")
        seed = spot.get("seed")
        if seed is not None and isinstance(box, (list, tuple)) and len(box) == 4 and not (
                box[0] <= seed[0] <= box[0] + box[2] and box[1] <= seed[1] <= box[1] + box[3]):
            errors.append(f"details spot {k}: seed {seed} is outside its box")
    return errors


def validate(cut: dict, project=None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block rendering."""
    errors: list[str] = []
    warnings: list[str] = []
    fmt = cut.get("format") or {}
    if not all(k in fmt for k in ("width", "height", "fps")):
        return ["format needs width, height and fps"], warnings
    fps = fmt["fps"]
    if fmt["width"] % 2 or fmt["height"] % 2:
        errors.append("format width and height must be even")
    if cut.get("duration", 0) <= 0:
        errors.append("duration must be positive")
    cuts = cut.get("cuts") or []
    if not cuts:
        return errors + ["the cut has no picture: add at least one entry to cuts"], warnings
    ids = [c.get("id") for c in cuts] + [x.get("id") for key in ("titles", "sounds", "voice", "captions", "hud") for x in cut.get(key) or []]
    for dup in sorted({i for i in ids if i and ids.count(i) > 1}):
        errors.append(f"id {dup} is used more than once")
    slots = timeline(cut)
    if slots[0]["f0"] != 0:
        errors.append(f"the first cut starts at {slots[0]['cut']['at']}s; picture must start at 0")
    shots = project.shots() if project else []
    for i, slot in enumerate(slots):
        entry, frames = slot["cut"], slot["f1"] - slot["f0"]
        name = entry.get("id", f"#{i + 1}")
        if frames <= 0:
            errors.append(f"{name}: starts at or after the next cut or the end of the film")
            continue
        if frames < 2:
            warnings.append(f"{name}: only {frames} frame long")
        t = transition_of(entry)
        if t["type"] not in TRANSITIONS:
            errors.append(f"{name}: unknown transition {t['type']!r}")
        elif t["type"] in OVERLAPS:
            if i == 0:
                errors.append(f"{name}: the first cut cannot dissolve in")
            elif t["frames"] >= frames:
                errors.append(f"{name}: dissolve of {t['frames']} frames is longer than the slot")
        for fx in entry.get("fx", []):
            fx_name = fx if isinstance(fx, str) else fx.get("name")
            if fx_name not in FX_NAMES:
                errors.append(f"{name}: unknown fx {fx_name!r} (known: {', '.join(FX_NAMES)})")
            elif fx_name == "details":
                errors.extend(f"{name}: {e}" for e in detail_problems(fx, frames))
        if "card" in entry:
            continue
        if "src" not in entry or "in" not in entry:
            errors.append(f"{name}: needs src and in, or card")
            continue
        s0, s1 = speed_pair(entry)
        if min(s0, s1) <= 0 or max(s0, s1) > 16:
            errors.append(f"{name}: speed must be within (0, 16]")
            continue
        if entry["in"] < 0:
            errors.append(f"{name}: in-point is negative")
        if entry.get("ramp", "linear") not in RAMPS:
            errors.append(f"{name}: unknown ramp {entry['ramp']!r} (known: {', '.join(RAMPS)})")
        if entry.get("interp", "nearest") not in INTERP:
            errors.append(f"{name}: unknown interp {entry['interp']!r} (known: {', '.join(INTERP)})")
        other = entry.get("intercut")
        if other:
            if "src" not in other or "in" not in other:
                errors.append(f"{name}: intercut needs src and in")
            elif project:
                try:
                    if float(other["in"]) + frames / fps > project.source(other["src"])["duration"] + 0.5 / fps:
                        errors.append(f"{name}: the intercut runs past the end of {other['src']}")
                except Exception:
                    errors.append(f"{name}: unknown intercut source {other['src']!r}")
        if not project:
            continue
        try:
            source = project.source(entry["src"])
        except Exception:
            errors.append(f"{name}: unknown source {entry['src']!r}")
            continue
        a, b = source_span(entry, frames, fps)
        if b > source["duration"] + 0.5 / fps:
            errors.append(f"{name}: runs {b - source['duration']:.2f}s past the end of {entry['src']} ({source['duration']:.2f}s)")
        # A slot should sit inside one logged shot; otherwise the source's own cut shows up mid-slot.
        for shot in shots:
            if shot["src"] == entry["src"] and a + 1.5 / fps < shot["start"] < b - 1.5 / fps:
                warnings.append(f"{name}: crosses a cut inside {entry['src']} at {shot['start']:.2f}s "
                                f"({shot['start'] - a:.2f}s into the slot)")
    total = cut["duration"]
    for title in cut.get("titles", []):
        if title.get("image"):
            image = Path(title["image"])
            if project and not (image if image.is_absolute() else project.root / image).exists():
                errors.append(f"{title.get('id')}: no such image {title['image']!r}")
        elif not str(title.get("text", "")).strip():
            errors.append(f"{title.get('id')}: title has no text")
        if title.get("at", 0) < 0 or title.get("at", 0) + title.get("dur", 0) > total + 1e-6:
            warnings.append(f"{title.get('id')}: title runs outside the film")
    for sound in cut.get("sounds", []):
        if "file" not in sound and sound.get("kind") not in SOUND_KINDS:
            errors.append(f"{sound.get('id')}: unknown sound kind {sound.get('kind')!r} (known: {', '.join(SOUND_KINDS)})")
        if not 0 <= sound.get("at", 0) <= total:
            warnings.append(f"{sound.get('id')}: sound starts outside the film")
    for item in cut.get("voice") or []:
        name = item.get("id", "voice")
        if "src" not in item and "file" not in item:
            errors.append(f"{name}: a voice entry needs src (a project voice) or file")
        elif "src" in item and project and not any(v["id"] == item["src"] for v in project.data.get("voices", [])):
            errors.append(f"{name}: unknown voice {item['src']!r} (workprint voice add FILE)")
        if not 0 <= item.get("at", 0) <= total:
            warnings.append(f"{name}: voice starts outside the film")
        try:
            from .vox import settings as treatment
            treatment(item.get("treat"))
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
    if cut.get("hud"):
        from .hud import problems as hud_problems
        more_errors, more_warnings = hud_problems(cut)
        errors += more_errors
        warnings += more_warnings
    if cut.get("captions"):
        from .captions import problems
        more_errors, more_warnings = problems(cut)
        errors += more_errors
        warnings += more_warnings
    music = cut.get("music")
    if music and project:
        if not project.data.get("music"):
            errors.append("the cut uses music but the project has none (workprint music --set FILE)")
        elif music.get("in", 0) + total > project.data["music"]["duration"] + 0.05:
            warnings.append("the music ends before the film does")
    return errors, warnings


def chunk_plan(cut: dict) -> list[dict]:
    """Group slots into render chunks.

    A slot of SOLO_FRAMES or more is its own chunk; runs of shorter slots (rapid cutting)
    share one. Grouping depends only on each slot's own length, so an edit to one part of
    the film never regroups another part.
    """
    chunks: list[dict] = []
    run: list[int] = []
    slots = timeline(cut)

    def flush():
        if run:
            chunks.append({"slots": list(run), "f0": slots[run[0]]["f0"], "f1": slots[run[-1]]["f1"]})
            run.clear()

    for i, slot in enumerate(slots):
        if slot["f1"] - slot["f0"] >= SOLO_FRAMES:
            flush()
            chunks.append({"slots": [i], "f0": slot["f0"], "f1": slot["f1"]})
        else:
            run.append(i)
    flush()
    return chunks


def diff(old: dict, new: dict) -> dict:
    """What changed between two versions of a cut, by id."""
    def index(cut, key):
        return {item.get("id"): item for item in cut.get(key, [])}

    report: dict = {}
    for key in ("cuts", "titles", "sounds"):
        a, b = index(old, key), index(new, key)
        entry = {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)),
                 "changed": sorted(i for i in set(a) & set(b) if a[i] != b[i])}
        if any(entry.values()):
            report[key] = entry
    other = [k for k in ("format", "duration", "music", "look", "audio") if old.get(k) != new.get(k)]
    if other:
        report["settings"] = other
    return report


def clone(cut: dict) -> dict:
    return copy.deepcopy(cut)
