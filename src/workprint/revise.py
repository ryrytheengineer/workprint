"""Revision operations: small, named changes to an existing cut.

Each operation edits the cut in place and returns a one-line description that is
stored in the cut's history. Ids are stable, so "replace c012" means the same slot
across versions, and the renderer re-renders only what an operation touched.
"""
from __future__ import annotations

import json

from . import music as music_mod
from .manifest import find, next_id, speed_pair, timeline
from .planner import _in_point
from .shots import shot_by_id


class ReviseError(ValueError):
    pass


def _slot(cut: dict, cut_id: str) -> tuple[int, dict, list[dict]]:
    slots = timeline(cut)
    for i, slot in enumerate(slots):
        if slot["cut"].get("id") == cut_id:
            return i, slot, slots
    raise ReviseError(f"no cut with id {cut_id!r}")


def replace(cut: dict, project, cut_id: str, shot: str | None = None, src: str | None = None, start: float | None = None) -> str:
    """Put different footage in a slot. The slot's timing does not change."""
    _, slot, _ = _slot(cut, cut_id)
    entry, fps = slot["cut"], cut["format"]["fps"]
    need = (slot["f1"] - slot["f0"]) / fps * sum(speed_pair(entry)) / 2
    if shot:
        logged = shot_by_id(project.shots(), shot)
        src = logged["src"]
        if start is None:
            start = _in_point(logged, need, 0.5, [])
        entry["shot"] = shot
    elif src:
        project.source(src)
        entry.pop("shot", None)
        if start is None:
            raise ReviseError("give --in when replacing by source id")
    else:
        raise ReviseError("give a shot or a source")
    entry.pop("card", None)
    entry["src"], entry["in"] = src, round(float(start), 3)
    return f"replace {cut_id} with {shot or src} from {entry['in']}s"


def slip(cut: dict, cut_id: str, delta: float) -> str:
    """Move the footage under a slot earlier or later without moving the slot."""
    entry = find(cut, "cuts", cut_id)
    if "in" not in entry:
        raise ReviseError(f"{cut_id} is a card")
    entry["in"] = round(max(0.0, entry["in"] + delta), 3)
    return f"slip {cut_id} by {delta:+.3f}s"


def roll(cut: dict, cut_id: str, by: float | None = None, to: float | None = None, analysis: dict | None = None,
         snap: float | None = None, keep_in: bool = False) -> str:
    """Move the cut point at the head of a slot. The slot before it gets longer or shorter."""
    i, slot, slots = _slot(cut, cut_id)
    if i == 0:
        raise ReviseError("the first cut starts the film and cannot be rolled")
    fps = cut["format"]["fps"]
    entry = slot["cut"]
    old = entry["at"]
    new = float(to) if to is not None else old + float(by or 0.0)
    if snap and analysis and cut.get("music"):
        offset = cut["music"].get("in", 0.0)
        new = music_mod.snap(analysis, new + offset, snap) - offset
    lo, hi = slots[i - 1]["f0"] / fps + 1 / fps, slot["f1"] / fps - 1 / fps
    if not lo <= new <= hi:
        raise ReviseError(f"{cut_id} can move between {lo:.3f}s and {hi:.3f}s; {new:.3f}s is outside")
    entry["at"] = round(new, 5)
    if "in" in entry and not keep_in:  # keep the incoming shot in sync with itself
        entry["in"] = round(max(0.0, entry["in"] + (new - old) * speed_pair(entry)[0]), 3)
    return f"roll {cut_id} from {old:.3f}s to {new:.3f}s"


def insert(cut: dict, project, at: float, shot: str | None = None, src: str | None = None, start: float | None = None) -> str:
    """Start a new slot at ``at``; it runs until the next existing cut."""
    fps = cut["format"]["fps"]
    if any(abs(c["at"] - at) < 0.5 / fps for c in cut["cuts"]):
        raise ReviseError(f"there is already a cut at {at:.3f}s; use replace")
    entry = {"id": next_id(cut, "cuts", "c"), "at": round(float(at), 5), "card": {}}
    cut["cuts"].append(entry)
    replace(cut, project, entry["id"], shot, src, start)
    return f"insert {entry['id']} at {at:.3f}s ({shot or src})"


def remove(cut: dict, item_id: str) -> str:
    """Remove a cut (the slot before it extends), a title, a sound, a caption or a placed voice."""
    for key in ("cuts", "titles", "sounds", "captions", "voice"):
        items = cut.get(key, [])
        for k, item in enumerate(items):
            if item.get("id") == item_id:
                if key == "cuts":
                    ordered = sorted(items, key=lambda c: c["at"])
                    if len(ordered) == 1:
                        raise ReviseError("cannot remove the only cut")
                    if ordered[0] is item:
                        ordered[1]["at"] = 0.0
                del items[k]
                return f"remove {item_id}"
    raise ReviseError(f"nothing with id {item_id!r}")


def swap(cut: dict, a: str, b: str) -> str:
    """Exchange what two slots show, leaving the cut points where they are."""
    ea, eb = find(cut, "cuts", a), find(cut, "cuts", b)
    keep = ("id", "at", "t")
    ca = {k: v for k, v in ea.items() if k not in keep}
    cb = {k: v for k, v in eb.items() if k not in keep}
    for entry, content in ((ea, cb), (eb, ca)):
        for k in [k for k in entry if k not in keep]:
            del entry[k]
        entry.update(content)
    return f"swap {a} and {b}"


def shift(cut: dict, start: float, by: float) -> str:
    """Ripple: move every cut, title, sound, voice and caption at or after ``start`` by ``by`` seconds, changing the film's length."""
    fps = cut["format"]["fps"]
    before = [c["at"] for c in cut["cuts"] if c["at"] < start - 0.5 / fps]
    moved = [c for c in cut["cuts"] if c["at"] >= start - 0.5 / fps and c["at"] > 0]
    if moved and before and min(c["at"] for c in moved) + by <= max(before):
        raise ReviseError("that shift would move a cut past the one before it")
    for key in ("cuts", "titles", "sounds", "voice", "captions"):
        for item in cut.get(key) or []:
            if item["at"] >= start - 0.5 / fps and not (key == "cuts" and item["at"] == 0):
                item["at"] = round(item["at"] + by, 5)
    cut["duration"] = round(cut["duration"] + by, 5)
    return f"shift everything from {start:.3f}s by {by:+.3f}s (music is not moved: check sync)"


def parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def assign(cut: dict, target: str, pairs: list[str]) -> str:
    """Set or clear fields: ``key=value`` (JSON or plain text), ``key=`` deletes. Target is an id, or look/music/audio/film."""
    if target in ("look", "music", "audio"):
        item = cut.get(target) or {}
        cut[target] = item
    elif target == "film":
        item = cut
    else:
        item = next((x for key in ("cuts", "titles", "sounds", "captions", "voice") for x in cut.get(key) or []
                     if x.get("id") == target), None)
        if item is None:
            raise ReviseError(f"nothing with id {target!r}")
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ReviseError(f"expected key=value, got {pair!r}")
        if value == "":
            item.pop(key, None)
        else:
            item[key] = parse_value(value)
    return f"set {target}: " + ", ".join(pairs)


def add(cut: dict, kind: str, pairs: list[str]) -> str:
    """Add a title, a sound or a caption from key=value pairs."""
    key, prefix = {"title": ("titles", "t"), "sound": ("sounds", "s"), "caption": ("captions", "k")}[kind]
    item = {"id": next_id(cut, key, prefix)}
    cut.setdefault(key, []).append(item)
    assign(cut, item["id"], pairs)
    if "at" not in item:
        raise ReviseError(f"a {kind} needs at=<seconds>")
    if kind == "title":
        item.setdefault("dur", 2.0)
    if kind == "caption":
        item.setdefault("style", "line")
        item.setdefault("dur", round(max(1.2, 0.4 * len(str(item.get("text", "")).split())), 2))
    return f"add {kind} {item['id']} at {item['at']}s"
