"""Evaluation: does the rendered film match the cut, the music and the brief?

The checker measures the finished file rather than trusting the plan. It re-detects
cuts in the render and compares them with the manifest (which exposes a source
clip's own hidden cut inside a slot), looks for black and frozen frames, measures
how the cut points sit on the musical grid, measures loudness, and summarises pacing.
It cannot judge taste; it reports facts for the editor to act on.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import ff, music as music_mod, sheets, shots
from .look import hex_bgr
from .manifest import alternate_frames, intercut_frames, speed_pair, timeline, transition_of, validate
from .titles import make as make_title
from .titles import schedule


def _runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for i, flag in enumerate(list(mask) + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def check(project, cut: dict, render_path, write_review: bool = True) -> dict:
    render_path = Path(render_path)
    fmt, fps = cut["format"], cut["format"]["fps"]
    slots = timeline(cut)
    total = slots[-1]["f1"]
    findings: list[dict] = []

    def note(level: str, text: str):
        findings.append({"level": level, "text": text})

    errors, warnings = validate(cut, project)
    for text in errors:
        note("fail", text)
    for text in warnings:
        note("warn", text)

    # ---- container facts ---------------------------------------------------------------------------
    info = ff.probe(render_path)
    scale = info["width"] / fmt["width"]
    if abs(info["height"] / fmt["height"] - scale) > 0.01:
        from .versions import size_for
        vw, vh = size_for(fmt, info["width"] / info["height"])
        if abs(vw / vh - info["width"] / info["height"]) < 0.01:
            fmt = {**fmt, "width": vw, "height": vh}
            note("info", f"checked as the {vw}x{vh} version of the cut")
        else:
            note("fail", f"aspect differs from the cut: {info['width']}x{info['height']} vs {fmt['width']}x{fmt['height']}")
    if abs(info["fps"] - fps) > 0.01:
        note("fail", f"frame rate is {info['fps']}, the cut asks for {fps}")
    if abs(info["video_duration"] - cut["duration"]) > 1.5 / fps:
        note("fail", f"picture runs {info['video_duration']:.3f}s, the cut is {cut['duration']:.3f}s")

    # ---- picture: cuts, black, frozen ------------------------------------------------------------
    sig = shots.frame_signals(render_path, {"fps": fps, "matrix": "bt709"})
    count = len(sig["hist"])
    if abs(count - total) > 1:
        note("fail", f"{count} frames decoded, {total} expected")
    found = set(shots.find_cuts(sig["hist"], sig["diff"], fps, min_len=2.5 / fps))
    planned, soft, expected_changes = [], set(), set()
    for i, slot in enumerate(slots):
        kind = transition_of(slot["cut"])["type"]
        if i > 0:
            if kind in ("cut", "flash"):
                planned.append(slot["f0"])
            else:  # a dissolve or dip changes the picture over several frames: any of them may register
                span = transition_of(slot["cut"])["frames"]
                soft.update(range(slot["f0"] - span, slot["f0"] + span + 1))
        for fx in slot["cut"].get("fx") or []:  # effect boundaries legitimately change the picture abruptly
            spec = {"name": fx} if isinstance(fx, str) else fx
            n = slot["f1"] - slot["f0"]
            for edge in (spec.get("from", 0), spec.get("to", n)):
                expected_changes.add(slot["f0"] + int(edge))
            if spec.get("name") == "xray-flicker":
                a, b = int(spec.get("from", 0)), int(spec.get("to", n))
                on = alternate_frames(b - a, 0, None, int(spec.get("every", 2)), spec.get("pattern"))
                expected_changes.update(slot["f0"] + a + k for k in range(b - a + 1) if (k in on) != (k - 1 in on))
        if slot["cut"].get("intercut"):
            n = slot["f1"] - slot["f0"]
            on = intercut_frames(slot["cut"], n, fps)
            expected_changes.update(slot["f0"] + k for k in range(n + 1) if (k in on) != (k - 1 in on))
    for item in schedule(cut.get("titles"), fps):
        if not item["fade_in"]:
            expected_changes.add(item["f0"])
        if not item["fade_out"]:
            expected_changes.add(item["f1"])

    for cue in cut.get("captions") or []:  # a caption arriving or leaving changes the picture on purpose
        if "at" in cue and cue.get("dur", 0) > 0:
            start = int(round(cue["at"] * fps))
            expected_changes.update([start, start + max(1, int(round(cue["dur"] * fps)))])
            expected_changes.update(int(round((cue["at"] + t) * fps)) for t, _ in cue.get("words") or [])

    def near(frame: int, pool) -> bool:
        return any(abs(frame - p) <= 1 for p in pool)

    confirmed = [f for f in planned if near(f, found)]
    invisible = [f for f in planned if not near(f, found)]
    unplanned = sorted(f for f in found if not near(f, planned) and not near(f, soft) and not near(f, expected_changes))
    for f in unplanned:
        slot = next((s for s in slots if s["f0"] <= f < s["f1"]), slots[-1])
        note("warn", f"unplanned picture change at {f / fps:.2f}s inside {slot['cut'].get('id')} "
                     f"({(f - slot['f0']) / fps:.2f}s in): the source may contain its own cut or a flash")
    for f in invisible:
        slot = next(s for s in slots if s["f0"] == f)
        note("info", f"the cut into {slot['cut'].get('id')} at {f / fps:.2f}s is barely visible: both sides look alike")

    card_or_dip = np.zeros(count, bool)
    still_ok = np.zeros(count, bool)
    for i, slot in enumerate(slots):
        a, b = slot["f0"], min(slot["f1"], count)
        entry = slot["cut"]
        if "card" in entry:
            card_or_dip[a:b] = still_ok[a:b] = True
        if entry.get("freeze"):
            still_ok[a:b] = True
        t = transition_of(entry)
        if t["type"] == "dip":
            card_or_dip[max(0, a - t["frames"]): a + t["frames"]] = True
    black = (sig["luma"] < 0.02) & (sig["peak"] < 0.08) & ~card_or_dip[:count]  # dark with a bright detail is not black
    for a, b in _runs(black, 2):
        note("warn", f"black picture from {a / fps:.2f}s to {b / fps:.2f}s")
    # Truly repeated frames only: a locked-off shot of a still subject changes little but not nothing.
    frozen = (sig["diff"] < 5e-5) & ~still_ok[:count]
    frozen[0] = False
    for a, b in _runs(frozen, 6):
        note("warn", f"picture frozen from {a / fps:.2f}s to {b / fps:.2f}s")

    # ---- music: where the cuts sit on the grid ---------------------------------------------------
    sync = None
    analysis = project.music()
    if cut.get("music") and analysis and len(analysis.get("beats", [])) > 4:
        offset = cut["music"].get("in", 0.0)
        tol = max(1.0 / fps, 0.045)
        beats, sixteenths = music_mod.grid(analysis, 1), music_mod.grid(analysis, 4)
        bars = np.array(analysis["bars"])
        rows = []
        for slot in slots[1:]:
            t = slot["f0"] / fps + offset
            rows.append({"id": slot["cut"].get("id"), "at": round(slot["f0"] / fps, 3),
                         "to_beat": round(float(np.abs(beats - t).min()), 3), "to_grid": round(float(np.abs(sixteenths - t).min()), 3),
                         "on_bar": bool(len(bars) and np.abs(bars - t).min() <= tol)})
        if rows:
            on_beat = sum(r["to_beat"] <= tol for r in rows)
            on_grid = sum(r["to_grid"] <= tol for r in rows)
            off = [r for r in rows if r["to_grid"] > tol]
            sync = {"cuts": len(rows), "on_beat": on_beat, "on_grid": on_grid, "on_bar": sum(r["on_bar"] for r in rows),
                    "tolerance_s": round(tol, 3), "off_grid": off}
            for r in off:
                note("info", f"{r['id']} at {r['at']:.2f}s is {r['to_grid'] * 1000:.0f} ms off the musical grid")

    # ---- sound -----------------------------------------------------------------------------------
    loud = None
    if info.get("has_audio"):
        loud = ff.loudness(render_path)
        target = (cut.get("audio") or {}).get("target_lufs", -14.0)
        if loud["lufs"] is not None and target is not None and abs(loud["lufs"] - target) > 1.5:
            note("warn", f"loudness is {loud['lufs']:.1f} LUFS, target {target:.1f}")
        if loud["true_peak"] is not None and loud["true_peak"] > -0.3:
            note("warn", f"true peak is {loud['true_peak']:.1f} dBTP: risk of clipping after re-encoding")
    elif cut.get("music") or cut.get("sounds"):
        note("fail", "the cut has sound but the render has no audio stream")

    # ---- pacing and repetition -------------------------------------------------------------------
    lengths = np.array([(s["f1"] - s["f0"]) / fps for s in slots if "card" not in s["cut"]])
    pacing = {"shots": int(len(lengths)), "mean_s": round(float(lengths.mean()), 2) if len(lengths) else 0,
              "median_s": round(float(np.median(lengths)), 2) if len(lengths) else 0,
              "shortest_s": round(float(lengths.min()), 2) if len(lengths) else 0,
              "longest_s": round(float(lengths.max()), 2) if len(lengths) else 0}
    spans: dict[str, list[tuple[float, float, str]]] = {}
    for slot in slots:
        entry = slot["cut"]
        if "src" not in entry:
            continue
        s0, s1 = speed_pair(entry)
        a = entry["in"]
        b = a + (slot["f1"] - slot["f0"]) / fps * (s0 + s1) / 2
        for (c, d, other) in spans.get(entry["src"], []):
            if min(b, d) - max(a, c) > 0.25:
                note("info", f"{entry.get('id')} reuses footage already seen in {other} ({entry['src']} {max(a, c):.1f}-{min(b, d):.1f}s)")
                break
        spans.setdefault(entry["src"], []).append((a, b, entry.get("id")))

    # ---- titles ----------------------------------------------------------------------------------
    for item in schedule(cut.get("titles"), fps):
        title = make_title(item["spec"], fmt["width"], fmt["height"], project.root)
        x0, y0, x1, y1 = title.box
        mx, my = 0.05 * fmt["width"], 0.05 * fmt["height"]
        if x0 < mx or y0 < my or x1 > fmt["width"] - mx or y1 > fmt["height"] - my:
            note("warn", f"title {item['spec'].get('id')} extends outside the 5% safe margin")
        mid = min(count - 1, (item["f0"] + item["f1"]) // 2)
        b, g, r = hex_bgr({**{"color": "#f4f1ea"}, **(item["spec"].get("style") or {})}["color"])
        text_luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        if (not item["spec"].get("image") and 0 <= mid < count and abs(text_luma - sig["luma"][mid]) < 0.25
                and not (item["spec"].get("style") or {}).get("shadow")):
            note("info", f"title {item['spec'].get('id')} sits on picture of similar brightness: check legibility")

    # ---- voice and captions ------------------------------------------------------------------------
    speech = None
    if cut.get("voice") or cut.get("captions"):
        from . import voice as voice_mod
        from .captions import compile_cue, style_of
        spoken = voice_mod.placed(project, cut)
        phrases = voice_mod.placed_phrases(project, cut)
        hard = [s["f0"] / fps for s in slots[1:] if transition_of(s["cut"])["type"] in ("cut", "flash")]
        inside = [(t, w) for t in hard for w in spoken if w["s"] + 0.06 < t < w["e"] - 0.06]
        led = sum(1 for a, _ in phrases if any(-0.25 <= a - t <= 0.12 for t in [0.0] + hard))
        from . import mix as mix_mod
        balance = (mix_mod.build(project, cut) or {}).get("voice_over_music_db") if cut.get("voice") else None
        speech = {"words": len(spoken), "phrases": len(phrases), "phrases_opening_on_a_cut": led, "cuts_inside_words": len(inside),
                  "captions": len(cut.get("captions") or []), "voice_over_music_db": balance}
        if balance is not None and balance < 6.0:
            note("warn", f"the voice sits only {balance:+.1f} dB above the music where they compete: it may be hard to follow. "
                         "Try `workprint set audio carve_db=-8`, a `treat=clear` on the voice, or more gain_db")
        for t, w in inside[:8]:
            note("info", f"the cut at {t:.2f}s lands inside the word {w['w']!r} ({w['s']:.2f}-{w['e']:.2f}s)")
        mx, my = 0.04 * fmt["width"], 0.04 * fmt["height"]
        for cue in cut.get("captions") or []:
            name, style = cue.get("id"), style_of(cue)
            pieces = compile_cue(cue, fps, fmt["width"], fmt["height"])
            for piece in pieces:
                x0, y0, x1, y1 = piece["block"].box()
                if x0 < mx or y0 < my or x1 > fmt["width"] - mx or y1 > fmt["height"] - my:
                    note("warn", f"caption {name} extends outside the 4% safe margin")
                    break
            mid = int(round((cue["at"] + cue["dur"] / 2) * fps))
            b, g, r = hex_bgr(style["color"])
            text_luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
            if 0 <= mid < count and abs(text_luma - sig["luma"][mid]) < 0.25 and not style.get("shadow") and not style.get("dim"):
                note("info", f"caption {name} sits on picture of similar brightness: check legibility")
            if cue.get("voice") and cue.get("words"):
                first = voice_mod.plain(cue["words"][0][1])
                said = [w for w in spoken if w["voice"] == cue["voice"] and voice_mod.plain(w["w"]) == first]
                if said:
                    drift = min((cue["at"] + cue["words"][0][0] - w["s"] for w in said), key=abs)
                    if abs(drift) > 1.5 / fps:
                        note("warn", f"caption {name} is {drift:+.2f}s off the voice: re-run `workprint captions`")

    levels = [f["level"] for f in findings]
    verdict = "FAIL" if "fail" in levels else "WARN" if "warn" in levels else "PASS"
    report = {"render": str(render_path), "verdict": verdict, "size": [info["width"], info["height"]], "fps": info["fps"],
              "duration": info["video_duration"], "frames": count,
              "cuts": {"planned_hard": len(planned), "confirmed": len(confirmed), "barely_visible": len(invisible), "unplanned": len(unplanned)},
              "music_sync": sync, "loudness": loud, "pacing": pacing, "speech": speech, "findings": findings}

    if write_review:
        folder = project.root / "review" / render_path.stem
        folder.mkdir(parents=True, exist_ok=True)
        frames, _ = sheets.read_small(render_path)
        report["storyboard"] = str(sheets.storyboard(cut, frames, folder / "storyboard.jpg"))
        if len(slots) > 1:
            report["cut_pairs"] = str(sheets.cut_pairs(cut, frames, folder / "cuts.jpg"))
        (folder / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def summary(report: dict) -> str:
    """A short plain-text account of a check report."""
    lines = [f"{report['verdict']}  {Path(report['render']).name}  {report['size'][0]}x{report['size'][1]} @ {report['fps']}  "
             f"{report['duration']:.2f}s  {report['frames']} frames"]
    c = report["cuts"]
    lines.append(f"cuts: {c['confirmed']}/{c['planned_hard']} hard cuts confirmed in the picture, "
                 f"{c['barely_visible']} barely visible, {c['unplanned']} unplanned")
    s = report.get("music_sync")
    if s:
        lines.append(f"music: {s['on_beat']}/{s['cuts']} cuts on a beat, {s['on_grid']}/{s['cuts']} on the 16th grid, "
                     f"{s['on_bar']} on a bar line (tolerance {s['tolerance_s'] * 1000:.0f} ms)")
    loud = report.get("loudness")
    if loud:
        lines.append(f"sound: {loud['lufs']} LUFS integrated, true peak {loud['true_peak']} dBTP, range {loud['lra']} LU")
    v = report.get("speech")
    if v:
        lines.append(f"voice: {v['words']} words in {v['phrases']} phrases, {v['phrases_opening_on_a_cut']} phrases open on a cut, "
                     f"{v['cuts_inside_words']} cuts land inside a word, {v['captions']} captions"
                     + (f", voice {v['voice_over_music_db']:+.1f} dB over the music" if v.get("voice_over_music_db") is not None else ""))
    p = report["pacing"]
    lines.append(f"pacing: {p['shots']} shots, median {p['median_s']}s, shortest {p['shortest_s']}s, longest {p['longest_s']}s")
    for f in report["findings"]:
        lines.append(f"  [{f['level']}] {f['text']}")
    for key in ("storyboard", "cut_pairs"):
        if report.get(key):
            lines.append(f"{key}: {report[key]}")
    return "\n".join(lines)
