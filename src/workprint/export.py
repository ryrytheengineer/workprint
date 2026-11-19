"""Timeline export for finishing in an editing application. Experimental.

Two formats: a CMX3600 EDL written directly, and OpenTimelineIO (``.otio``) when the
optional ``opentimelineio`` package is installed. Both carry cut points, source
ranges and clip names. Grades, effects, titles and the mix do not travel; speed
changes are noted but not applied in the EDL. Source timecode is assumed to start
at zero. Import into Premiere Pro and DaVinci Resolve has not been verified yet.
"""
from __future__ import annotations

from pathlib import Path

from .manifest import source_span, speed_pair, timeline


def _timecode(frames: int, fps: float) -> str:
    base = int(round(fps))
    return "{:02d}:{:02d}:{:02d}:{:02d}".format(frames // (3600 * base), frames // (60 * base) % 60, frames // base % 60, frames % base)


def edl(project, cut: dict, path) -> Path:
    fps = cut["format"]["fps"]
    lines = [f"TITLE: {cut.get('title') or project.data.get('name', 'WORKPRINT')}", "FCM: NON-DROP FRAME", ""]
    for n, slot in enumerate(timeline(cut), start=1):
        entry = slot["cut"]
        frames = slot["f1"] - slot["f0"]
        if "src" not in entry:
            lines.append(f"{n:03d}  BL       V     C        {_timecode(0, fps)} {_timecode(frames, fps)} "
                         f"{_timecode(slot['f0'], fps)} {_timecode(slot['f1'], fps)}")
            continue
        a, b = source_span(entry, frames, fps)
        src_in, src_out = int(round(a * fps)), int(round(a * fps)) + max(1, int(round((b - a) * fps)))
        lines.append(f"{n:03d}  {entry['src']:<8} V     C        {_timecode(src_in, fps)} {_timecode(src_out, fps)} "
                     f"{_timecode(slot['f0'], fps)} {_timecode(slot['f1'], fps)}")
        lines.append(f"* FROM CLIP NAME: {Path(project.source(entry['src'])['path']).name}")
        if speed_pair(entry) != (1.0, 1.0):
            lines.append(f"* WORKPRINT SPEED: {entry['speed']} (not applied in this EDL)")
        if entry.get("note"):
            lines.append(f"* WORKPRINT {entry.get('id', '')}: {entry['note']}")
    path = Path(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def otio(project, cut: dict, path) -> Path:
    try:
        import opentimelineio as o
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("OpenTimelineIO is not installed. Install it with: pip install opentimelineio") from exc
    fps = cut["format"]["fps"]
    video = o.schema.Track(name="V1", kind=o.schema.TrackKind.Video)
    for slot in timeline(cut):
        entry = slot["cut"]
        frames = slot["f1"] - slot["f0"]
        span = o.opentime.TimeRange(o.opentime.RationalTime(0, fps), o.opentime.RationalTime(frames, fps))
        if "src" not in entry:
            video.append(o.schema.Gap(source_range=span))
            continue
        source = project.source(entry["src"])
        a, _ = source_span(entry, frames, fps)
        media = o.schema.ExternalReference(
            target_url=project.path_of(source).as_uri(),
            available_range=o.opentime.TimeRange(o.opentime.RationalTime(0, fps), o.opentime.RationalTime(source["duration"] * fps, fps)))
        clip = o.schema.Clip(name=f"{entry.get('id', '')} {Path(source['path']).name}", media_reference=media,
                             source_range=o.opentime.TimeRange(o.opentime.RationalTime(round(a * fps), fps), o.opentime.RationalTime(frames, fps)))
        s0, s1 = speed_pair(entry)
        if (s0, s1) != (1.0, 1.0):
            clip.effects.append(o.schema.LinearTimeWarp(time_scalar=(s0 + s1) / 2))
        clip.metadata["workprint"] = {k: entry[k] for k in ("id", "note", "shot", "grade", "fx", "move") if k in entry}
        video.append(clip)
    tracks = [video]
    if cut.get("music") and project.music_path():
        audio = o.schema.Track(name="A1", kind=o.schema.TrackKind.Audio)
        audio.append(o.schema.Clip(
            name=project.music_path().name, media_reference=o.schema.ExternalReference(target_url=project.music_path().as_uri()),
            source_range=o.opentime.TimeRange(o.opentime.RationalTime(round(cut["music"].get("in", 0.0) * fps), fps),
                                              o.opentime.RationalTime(round(cut["duration"] * fps), fps))))
        tracks.append(audio)
    doc = o.schema.Timeline(name=cut.get("title") or project.data.get("name", "workprint"), tracks=tracks)
    for title in cut.get("titles", []):
        video.markers.append(o.schema.Marker(name=str(title.get("text", ""))[:60], marked_range=o.opentime.TimeRange(
            o.opentime.RationalTime(round(title["at"] * fps), fps), o.opentime.RationalTime(round(title.get("dur", 1) * fps), fps))))
    path = Path(path)
    o.adapters.write_to_file(doc, str(path))
    return path
