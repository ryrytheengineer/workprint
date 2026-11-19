"""Command line for Workprint. Every command works on a project directory (``-p``, default: here)."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .project import Project, ProjectError, read_json, write_json


def _project(args) -> Project:
    return Project(args.project)


def _save(project: Project, cut: dict, message: str, force: bool = False) -> int:
    """Validate, save a new version, and say what a render would have to redo."""
    from .manifest import normalize, validate
    from .render import plan
    normalize(cut)
    errors, warnings = validate(cut, project)
    for text in errors:
        print(f"  error: {text}")
    for text in warnings:
        print(f"  warning: {text}")
    if errors and not force:
        print("not saved: fix the errors above (or pass --force)")
        return 1
    n = project.save_cut(cut, message)
    job = plan(project, cut, *_quality(True))
    print(f"saved v{n:04d}: {message}")
    print(f"next proxy render: {len(job['todo'])} of {len(job['ctx'].chunks)} chunks to render "
          f"({job['frames_todo']} of {job['frames_total']} frames), the rest reused")
    return 0


# ---- setup -----------------------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    ok = True
    print(f"workprint {__version__}  python {platform.python_version()}  {platform.system()} {platform.machine()}")
    hints = {"Darwin": "brew install ffmpeg", "Linux": "sudo apt install ffmpeg   (or your distribution's package)",
             "Windows": "winget install Gyan.FFmpeg"}
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if not path:
            ok = False
            print(f"  missing  {name}: install with `{hints.get(platform.system(), 'see https://ffmpeg.org/download.html')}`")
            continue
        version = subprocess.run([path, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        print(f"  ok       {name}: {version[:60]}")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        for enc, why in (("libx264", "H.264 picture"), ("aac", "AAC sound")):
            found = f" {enc} " in encoders
            ok &= found
            print(f"  {'ok     ' if found else 'missing'}  encoder {enc} ({why})")
    for module, package in (("numpy", "numpy"), ("scipy", "scipy"), ("cv2", "opencv-python-headless"), ("PIL", "Pillow")):
        try:
            mod = __import__(module)
            print(f"  ok       {package} {getattr(mod, '__version__', '')}")
        except ImportError:
            ok = False
            print(f"  missing  {package}: pip install {package}")
    try:
        import opentimelineio
        print(f"  ok       opentimelineio {opentimelineio.__version__} (optional: .otio export)")
    except ImportError:
        print("  optional opentimelineio not installed (.otio export unavailable; EDL export still works)")
    from .voice import tools
    have = tools()
    if all(have.values()):
        print("  ok       voice tools (optional: transcription and word timing)")
    else:
        lacking = ", ".join(k for k, v in have.items() if not v)
        print(f"  optional voice tools not installed ({lacking}): captions then need a script or a word file. `workprint voice setup`")
    print("ready" if ok else "not ready: install the missing items above")
    return 0 if ok else 1


def cmd_init(args) -> int:
    width, height = (int(v) for v in args.size.lower().split("x"))
    brief = Path(args.brief[1:]).read_text(encoding="utf-8") if args.brief and args.brief.startswith("@") else args.brief
    project = Project.create(args.dir, args.footage, args.music, width, height, args.fps, args.name, brief)
    total = sum(s["duration"] for s in project.data["sources"])
    print(f"project {project.root}: {len(project.data['sources'])} source(s), {total:.1f}s of footage, "
          f"{'music set' if project.data['music'] else 'no music'}, {width}x{height} @ {args.fps}")
    print("next: workprint ingest")
    return 0


def cmd_add(args) -> int:
    project = _project(args)
    added = project.add_footage(args.footage)
    project.save()
    print(f"added {len(added)} source(s): {', '.join(s['id'] for s in added) or 'none (already known)'}; run `workprint ingest`")
    return 0


def cmd_ingest(args) -> int:
    from . import sheets, shots
    project = _project(args)
    started = time.time()
    found = shots.ingest(project)
    print(f"{len(found)} shots logged in {time.time() - started:.1f}s -> {project.log_dir / 'shots.json'}")
    if not args.no_sheets:
        for path in sheets.contact_sheets(project):
            print(f"contact sheet: {path}")
        print("next: look at the contact sheets, then record what you see with `workprint log apply notes.json`")
    return 0


def cmd_sheets(args) -> int:
    from . import sheets
    for path in sheets.contact_sheets(_project(args), args.sources or None):
        print(path)
    return 0


def cmd_log(args) -> int:
    project = _project(args)
    shots = project.shots()
    if args.action == "apply":
        notes = read_json(Path(args.target))
        known = {s["id"]: s for s in shots}
        missing = [k for k in notes if k not in known]
        for shot_id, fields in notes.items():
            if shot_id in known:
                known[shot_id].update({k: v for k, v in fields.items() if k in ("desc", "tags", "rating")})
        project.save_shots(shots)
        print(f"updated {len(notes) - len(missing)} shot(s)" + (f"; unknown ids: {', '.join(missing)}" if missing else ""))
        return 0
    if args.action == "set":
        shot = next((s for s in shots if s["id"] == args.target), None)
        if not shot:
            print(f"unknown shot {args.target}")
            return 1
        if args.desc is not None:
            shot["desc"] = args.desc
        if args.tags is not None:
            shot["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
        if args.rating is not None:
            shot["rating"] = args.rating
        project.save_shots(shots)
        print(f"{shot['id']}: rated {shot['rating']}, tags {shot['tags']}, {shot['desc']!r}")
        return 0
    rows = [s for s in shots if (not args.src or s["src"] == args.src) and (args.min_rating is None or (s.get("rating") or 0) >= args.min_rating)]
    if args.json:
        print(json.dumps([{k: v for k, v in s.items() if k != "curve"} for s in rows], indent=1))
        return 0
    print(f"{'shot':<10}{'start':>8}{'dur':>7}{'motion':>8}{'cam':>6}{'luma':>6}  rating  tags / description")
    for s in rows:
        rating = "-" if s.get("rating") is None else s["rating"]
        print(f"{s['id']:<10}{s['start']:>8.2f}{s['dur']:>7.2f}{s['motion']:>8.2f}{s['camera']:>6.2f}{s['luma']:>6.2f}  {rating!s:<6}  "
              f"{','.join(s.get('tags', []))}  {s.get('desc', '')}"[:160])
    return 0


def cmd_look(args) -> int:
    from . import sheets, shots
    project = _project(args)
    print(sheets.filmstrip(project, shots.shot_by_id(project.shots(), args.shot), args.n, start=args.start, end=args.end))
    return 0


def cmd_frame(args) -> int:
    import cv2
    from . import ff
    project = _project(args)
    frame = ff.grab_frame(project.path_of(project.source(args.src)), args.t, args.width)
    out = Path(args.out) if args.out else project.log_dir / "frames" / f"{args.src}_{args.t:.2f}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(out)
    return 0


def cmd_music(args) -> int:
    from . import music
    project = _project(args)
    if args.set:
        project.set_music(args.set)
        project.save()
    path = project.music_path()
    if not path:
        print("the project has no music: workprint music --set FILE")
        return 1
    started = time.time()
    analysis = music.analyze(path)
    write_json(project.log_dir / "music.json", analysis)
    if args.json:
        print(json.dumps({k: v for k, v in analysis.items() if k not in ("beats", "hits")}, indent=1))
        return 0
    print(f"{path.name}: {analysis['duration']:.1f}s, {analysis['tempo']} BPM (could also be read as {analysis['tempo_alternates']}), "
          f"{analysis['key']['name']}, {len(analysis['beats'])} beats, {len(analysis['bars'])} bars "
          f"(bar-line confidence {analysis['bar_phase_confidence']}) in {time.time() - started:.1f}s")
    for s in analysis["sections"]:
        print(f"  {s['from']:>7.2f}-{s['to']:<7.2f} bars {s['bars'][0]:>3}-{s['bars'][1]:<3} energy {s['energy']:.2f}  {s['label']}")
    for d in analysis["drops"]:
        print(f"  drop at {d['t']:.2f}s (bar {d['bar']}, strength {d['strength']})")
    drums = analysis.get("drums") or {}
    print("  drum hits found: " + ", ".join(f"{len(drums.get(k, []))} {k}" for k in ("kick", "snare", "hat")))
    return 0


def _voice_report(entry: dict, analysis: dict) -> None:
    words, phrases = analysis["words"], analysis["phrases"]
    how = analysis["method"] + (", approximate" if analysis.get("approximate") else "")
    print(f"{entry['id']} {Path(entry['path']).name}: {analysis['duration']:.1f}s, {len(words)} words in {len(phrases)} phrases ({how})")
    for n, (a, b) in enumerate(phrases, 1):
        said = " ".join(w["w"] for w in words if a - 0.05 <= w["s"] < b)
        print(f"  phrase {n:>2}  {a:>7.2f}-{b:<7.2f} {said}")
    if words:
        print("  words: " + "  ".join(f"{w['w']} {w['s']:.2f}" for w in words))
        leaned = sorted(words, key=lambda w: -w.get("stress", 0))[:max(3, len(words) // 6)]
        print("  leaned on (level and length, not meaning): " + ", ".join(f"{w['w']} {w['s']:.2f}" for w in sorted(leaned, key=lambda w: w["s"])))
    for text in analysis.get("notes", []):
        print(f"  note: {text}")


def cmd_voice(args) -> int:
    from . import voice
    if args.action == "setup":
        have = voice.tools()
        if all(have.values()):
            print(f"voice tools are installed (model in {voice.model_dir()})")
            return 0
        m = voice.MODEL
        if not args.yes:
            print("voice setup would install:")
            if not (have["aligner"] and have["recognizer"]):
                print(f"  Python packages from PyPI: {', '.join(voice.PACKAGES)}")
            if not have["model"]:
                print(f"  speech model {m['name']} ({m['bytes'] / 1e6:.0f} MB download, about 660 MB on disk)")
                print(f"    from {m['url']}")
                print(f"    licence: {m['license']}")
                print(f"    into {voice.model_dir()}, used only if its SHA-256 matches the one pinned in Workprint")
            print("nothing is sent anywhere: recognition runs on this machine. Run `workprint voice setup --yes` to install.")
            return 1
        have = voice.setup()
        print("installed: " + ", ".join(k for k, v in have.items() if v))
        return 0 if all(have.values()) else 1
    project = _project(args)
    if args.action == "add":
        if not args.target:
            raise ValueError("voice add needs a file")
        entry = project.add_voice(args.target)
        project.save()
        script = args.script
        if script and script.startswith("@"):
            script = Path(script[1:]).expanduser().read_text(encoding="utf-8")
        started = time.time()
        analysis = voice.analyze(project.path_of(entry), script, args.words, args.pause, not args.no_model)
        write_json(project.log_dir / f"voice-{entry['id']}.json", analysis)
        _voice_report(entry, analysis)
        print(f"  read in {time.time() - started:.1f}s; place it with `workprint voice place {entry['id']} --at SECONDS`")
        return 0
    if args.action == "show":
        entries = [project.voice(args.target)] if args.target else project.data.get("voices", [])
        if not entries:
            print("the project has no voice: workprint voice add FILE")
            return 1
        for entry in entries:
            analysis = project.voice_log(entry["id"])
            if args.json:
                print(json.dumps({"id": entry["id"], **analysis}, indent=1))
            elif analysis:
                _voice_report(entry, analysis)
        return 0
    if args.action == "throw":  # echo one word of a placed voice, in time with the music
        cut = project.cut()
        item = next((v for v in cut.get("voice") or [] if v.get("id") == args.target), None)
        if item is None or not args.word:
            raise ValueError("voice throw needs a placed voice id (v001) and --word WORD")
        name, _, nth = args.word.partition(":")
        said = [w for w in voice.placed(project, cut, args.target) if voice.plain(w["w"]) == voice.plain(name)]
        if not said or int(nth or 1) > len(said):
            raise ValueError(f"{args.word!r} is not said in {args.target}")
        word = said[int(nth or 1) - 1]
        tempo = (project.music() or {}).get("tempo")
        delay = round(args.beats * 60.0 / float(tempo), 4) if tempo else 0.3
        item.setdefault("throws", []).append({"word": word["w"], "at": word["s"], "dur": round(word["e"] - word["s"], 3),
                                              "delay": delay, "repeats": args.repeats})
        print(f"{args.target}: {word['w']!r} at {word['s']:.2f}s echoes {args.repeats} times, {delay:.3f}s apart")
        return _save(project, cut, args.message or f"echo throw on {word['w']!r}", args.force)
    # place: put (part of) a voice on the timeline so that its first word starts at --at
    from .manifest import next_id
    entry, log = project.voice(args.target or ""), project.voice_log(args.target or "")
    if args.at is None:
        raise ValueError("voice place needs --at SECONDS (when the first word should land)")
    start, end = args.start, args.end
    if args.phrase:
        first, _, last = args.phrase.partition("-")
        chosen = log.get("phrases", [])[int(first) - 1:int(last or first)]
        if not chosen:
            raise ValueError(f"{entry['id']} has {len(log.get('phrases', []))} phrases")
        start, end = max(0.0, chosen[0][0] - 0.12), min(entry["duration"], chosen[-1][1] + 0.2)
    start = 0.0 if start is None else start
    end = entry["duration"] if end is None else end
    inside = voice.within(log, start, end)
    lead = (inside[0]["s"] - start) if inside else 0.0
    cut = project.cut()
    item = {"id": next_id(cut, "voice", "v"), "src": entry["id"], "at": round(max(0.0, args.at - lead), 3), "in": round(start, 3),
            "dur": round(end - start, 3), "gain_db": args.gain}
    cut.setdefault("voice", []).append(item)
    said = voice.text_of(inside)
    print(f"{item['id']}: {entry['id']} {start:.2f}-{end:.2f}s placed at {item['at']:.2f}s; first word lands at {item['at'] + lead:.2f}s"
          + (f': "{said[:70]}"' if said else ""))
    return _save(project, cut, args.message or f"place voice {entry['id']} at {item['at']:.2f}s", args.force)


def cmd_captions(args) -> int:
    from . import voice
    from .captions import from_words
    from .manifest import next_id
    project = _project(args)
    cut = project.cut()
    words = voice.placed(project, cut, args.voice)
    if not words:
        print("no placed voice with word times: `workprint voice add FILE`, then `workprint voice place ID --at SECONDS`")
        return 1
    punch = [p.strip() for p in (args.punch or "").split(",") if p.strip()]
    ids = sorted({w["voice"] for w in words})
    if not args.keep:  # replace what an earlier run made for these voices; hand-made cues are left alone
        cut["captions"] = [c for c in cut.get("captions") or [] if c.get("voice") not in ids]
        cut["sounds"] = [s for s in cut.get("sounds") or [] if s.get("voice") not in ids]
    made = []
    for voice_id in ids:
        for cue in from_words([w for w in words if w["voice"] == voice_id], args.style, punch, voice=voice_id, fps=cut["format"]["fps"]):
            cue = {"id": next_id(cut, "captions", "k"), **cue}
            cut.setdefault("captions", []).append(cue)
            made.append(cue)
    for cue in made:
        print(f"  {cue['id']}  {cue['at']:>7.2f}-{cue['at'] + cue['dur']:<7.2f} {cue['style']:<6} {cue['text']}")
    hits = [c for c in made if c["style"] == "punch"]
    if args.accent and hits:  # a different designed hit under each punch word, tuned to the music
        kit = [("impact", 0, 1.0), ("sub", 7, 1.0), ("boom", 0, 0.9), ("impact", 5, 1.15), ("sub", 3, 1.0), ("boom", 7, 1.1)]
        root = ((project.music() or {}).get("key") or {}).get("root")
        for n, cue in enumerate(hits):
            kind, step, weight = kit[n % len(kit)]
            sound = {"id": next_id(cut, "sounds", "s"), "at": cue["at"], "kind": kind, "db": -9, "weight": weight,
                     "note": f"accent: {cue['text']}", "voice": cue["voice"]}
            if root is not None:
                sound["pitch"] = (int(root) + step) % 12
            cut.setdefault("sounds", []).append(sound)
        print(f"  {len(hits)} accents added under the punch words")
    missing = [p for p in punch if not any(voice.plain(p.split(':')[0]) == voice.plain(c["text"]) for c in hits)]
    if missing:
        print(f"  not found in the voice: {', '.join(missing)}")
    return _save(project, cut, args.message or f"captions ({args.style}) for {', '.join(ids)}", args.force)


# ---- cutting ---------------------------------------------------------------------------------------

def cmd_draft(args) -> int:
    from . import planner, profile
    project = _project(args)
    structure = read_json(Path(args.structure))
    if args.profile:
        structure = profile.apply(structure, read_json(Path(args.profile)))
    cut = planner.draft(project, structure)
    return _save(project, cut, args.message or f"first assembly from {Path(args.structure).name}", args.force)


def _quality(proxy: bool, crf: int | None = None) -> tuple[float, int, str]:
    """Scale, CRF and x264 preset: delivery quality by default, small and fast for previews."""
    if proxy:
        return 0.5, crf or 23, "veryfast"
    return 1.0, crf or 20, "medium"


def cmd_validate(args) -> int:
    from .manifest import validate
    project = _project(args)
    errors, warnings = validate(project.cut(), project)
    for text in errors:
        print(f"error: {text}")
    for text in warnings:
        print(f"warning: {text}")
    print("valid" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


def cmd_plan(args) -> int:
    from .render import plan
    project = _project(args)
    job = plan(project, project.cut(), *_quality(args.proxy))
    print(f"{len(job['todo'])} of {len(job['ctx'].chunks)} chunks to render ({job['frames_todo']} of {job['frames_total']} frames)")
    return 0


def cmd_render(args) -> int:
    from .render import render
    project = _project(args)
    scale, crf, preset = _quality(args.proxy, args.crf)
    stats = render(project, project.cut(), args.out, scale, crf, preset, args.jobs, aspect=args.aspect)
    for text in stats["warnings"]:
        print(f"warning: {text}")
    if stats["underrun_frames"]:
        print(f"warning: {stats['underrun_frames']} frame(s) held because a source ran out")
    print(f"rendered {stats['frames_rendered']} of {stats['frames']} frames ({stats['chunks_rendered']} chunks rendered, "
          f"{stats['chunks_reused']} reused) in {stats['seconds']}s")
    if stats["audio"]:
        print(f"mix: {stats['audio']['lufs']} LUFS, true peak {stats['audio']['true_peak']} dBTP")
    print(stats["out"])
    if args.json:
        print(json.dumps(stats))
    return 0


def cmd_intercut(args) -> int:
    from . import revise
    project = _project(args)
    cut = project.cut()
    entry = revise._slot(cut, args.cut)[1]["cut"]
    if args.off:
        entry.pop("intercut", None)
        return _save(project, cut, args.message or f"{args.cut}: intercut removed", args.force)
    if args.shot:
        shot = next((s for s in project.shots() if s["id"] == args.shot), None)
        if shot is None:
            raise ValueError(f"unknown shot {args.shot!r}")
        src, start = shot["src"], shot["start"] if args.start is None else args.start
    elif args.src and args.start is not None:
        src, start = args.src, args.start
    else:
        raise ValueError("intercut needs --shot ID, or --src SOURCE --in SECONDS, or --off")
    spec = {"src": src, "in": round(float(start), 3), "every": args.every}
    if args.begin:
        spec["from"] = args.begin
    if args.end is not None:
        spec["to"] = args.end
    entry["intercut"] = spec
    return _save(project, cut, args.message or f"{args.cut}: flicker to {src} every {args.every} frames", args.force)


def cmd_reframe(args) -> int:
    from . import versions
    project = _project(args)
    cut = project.cut()
    tag, ratio = versions.parse(args.aspect)
    only = [s.strip() for s in args.slots.split(",")] if args.slots else None
    done = versions.propose(project, cut, tag, ratio, only, args.redo)
    for cut_id, focus in done:
        print(f"  {cut_id}  focus_{tag} = {focus}")
    target = versions.sheet(project, cut, tag, ratio, project.root / "review" / f"reframe-{tag}.jpg")
    w, h = versions.size_for(cut["format"], ratio)
    print(f"{len(done)} slots given a focus for {tag} ({w}x{h}). Look at {target} and correct any with "
          f"`workprint set ID focus_{tag}=[x,y]` (0 = left/top, 1 = right/bottom), then `workprint render --aspect {args.aspect}`")
    if not done:
        return 0
    return _save(project, cut, args.message or f"reframe for {tag}", args.force)


def cmd_check(args) -> int:
    from . import check
    project = _project(args)
    render_path = Path(args.render) if args.render else max((project.root / "renders").glob("*.mp4"), key=lambda p: p.stat().st_mtime, default=None)
    if not render_path:
        print("nothing rendered yet: workprint render")
        return 1
    report = check.check(project, project.cut(), render_path)
    print(json.dumps(report, indent=1) if args.json else check.summary(report))
    return 1 if report["verdict"] == "FAIL" else 0


def cmd_history(args) -> int:
    for v in _project(args).history():
        print(f"v{v['n']:04d}  {v['saved']}  {v['message']}")
    return 0


def cmd_diff(args) -> int:
    from .manifest import diff
    project = _project(args)
    b = args.b or project.version()
    a = args.a or b - 1
    if a < 1:
        print("nothing to compare yet")
        return 0
    print(f"v{a:04d} -> v{b:04d}: " + json.dumps(diff(project.load_version(a), project.load_version(b))))
    return 0


def cmd_undo(args) -> int:
    project = _project(args)
    n = project.version()
    if n < 2:
        print("nothing to undo")
        return 1
    return _save(project, project.load_version(n - 1), f"undo v{n:04d} (back to v{n - 1:04d})")


def cmd_revise(args) -> int:
    from . import revise
    project = _project(args)
    cut = project.cut()
    try:
        if args.cmd == "replace":
            message = revise.replace(cut, project, args.cut, args.shot, args.src, args.start)
        elif args.cmd == "slip":
            message = revise.slip(cut, args.cut, args.delta)
        elif args.cmd == "roll":
            message = revise.roll(cut, args.cut, args.by, args.to, project.music(), args.snap, args.keep_in, args.on)
        elif args.cmd == "insert":
            message = revise.insert(cut, project, args.at, args.shot, args.src, args.start)
        elif args.cmd == "remove":
            message = revise.remove(cut, args.id)
        elif args.cmd == "swap":
            message = revise.swap(cut, args.a, args.b)
        elif args.cmd == "shift":
            message = revise.shift(cut, args.start, args.by)
        elif args.cmd == "set":
            message = revise.assign(cut, args.target, args.pairs)
        else:
            message = revise.add(cut, args.kind, args.pairs)
    except (revise.ReviseError, KeyError) as exc:
        print(f"not changed: {exc}")
        return 1
    return _save(project, cut, args.message or message, args.force)


def cmd_profile(args) -> int:
    from . import profile
    result = profile.build(args.references)
    write_json(Path(args.out), result)
    print(profile.describe(result))
    print(f"profile written to {args.out}: read it, correct the preferences, then `workprint draft --profile {args.out}`")
    return 0


def cmd_export(args) -> int:
    from . import export
    project = _project(args)
    cut = project.cut()
    if not (args.edl or args.otio):
        print("give --edl FILE and/or --otio FILE")
        return 1
    if args.edl:
        print(export.edl(project, cut, args.edl))
    if args.otio:
        print(export.otio(project, cut, args.otio))
    return 0


def cmd_clean(args) -> int:
    project = _project(args)
    size = sum(f.stat().st_size for f in project.cache_dir.rglob("*") if f.is_file())
    shutil.rmtree(project.cache_dir)
    print(f"removed {size / 1e6:.1f} MB of cached chunks and mixes (sources, cuts and renders untouched)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workprint", description="A cinematic editing engine for Claude Code.")
    parser.add_argument("--version", action="version", version=f"workprint {__version__}")
    parser.add_argument("-p", "--project", default=".", help="project directory (default: current directory)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def command(name, func, help_text):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        return p

    def revision(name, help_text):
        p = command(name, cmd_revise, help_text)
        p.add_argument("-m", "--message")
        p.add_argument("--force", action="store_true", help="save even if validation reports errors")
        return p

    command("doctor", cmd_doctor, "check that everything Workprint needs is installed")
    p = command("init", cmd_init, "create a project from footage, music and a brief")
    p.add_argument("dir")
    p.add_argument("--footage", nargs="+", required=True, help="video files and/or folders")
    p.add_argument("--music")
    p.add_argument("--size", default="1920x1080")
    p.add_argument("--fps", type=float, default=24.0)
    p.add_argument("--name")
    p.add_argument("--brief", help="the brief as text, or @file")
    command("add", cmd_add, "add more footage to the project").add_argument("footage", nargs="+")
    command("ingest", cmd_ingest, "find shots, measure them, make contact sheets").add_argument("--no-sheets", action="store_true")
    command("sheets", cmd_sheets, "(re)make contact sheets").add_argument("sources", nargs="*")
    p = command("log", cmd_log, "show the shot log, or record notes: `log set SHOT ...`, `log apply FILE.json`")
    p.add_argument("action", nargs="?", choices=["show", "set", "apply"], default="show")
    p.add_argument("target", nargs="?")
    p.add_argument("--desc")
    p.add_argument("--tags")
    p.add_argument("--rating", type=float)
    p.add_argument("--src")
    p.add_argument("--min-rating", type=float)
    p.add_argument("--json", action="store_true")
    p = command("look", cmd_look, "filmstrip of one shot for a closer look")
    p.add_argument("shot")
    p.add_argument("-n", type=int, default=8)
    p.add_argument("--from", dest="start", type=float, help="look at part of the shot: source time in seconds")
    p.add_argument("--to", dest="end", type=float)
    p = command("frame", cmd_frame, "save one frame of a source")
    p.add_argument("src")
    p.add_argument("t", type=float)
    p.add_argument("--width", type=int)
    p.add_argument("--out")
    p = command("music", cmd_music, "analyse the music: tempo, bars, sections, drops")
    p.add_argument("--set", help="use this file as the project's music")
    p.add_argument("--json", action="store_true")
    p = command("voice", cmd_voice, "read a voice-over (phrases, words, times) and place it: voice setup|add|show|place")
    p.add_argument("action", choices=["setup", "add", "show", "place", "throw"])
    p.add_argument("target", nargs="?", help="a file for add; a voice id (V01) for show and place")
    p.add_argument("--script", help="the words spoken, as text or @file: used as the spelling, and for timing if nothing better")
    p.add_argument("--words", help="word times you already have: Whisper-style JSON, SRT or VTT")
    p.add_argument("--pause", type=float, default=0.35, help="a silence this long ends a phrase")
    p.add_argument("--no-model", action="store_true", help="do not transcribe even if the speech model is installed")
    p.add_argument("--yes", action="store_true", help="setup: go ahead and install")
    p.add_argument("--json", action="store_true")
    p.add_argument("--at", type=float, help="place: film time at which the first word starts")
    p.add_argument("--from", dest="start", type=float, help="place: use the recording from this time")
    p.add_argument("--to", dest="end", type=float)
    p.add_argument("--phrase", help="place: use phrase N, or N-M")
    p.add_argument("--gain", type=float, default=0.0)
    p.add_argument("--word", help="throw: the word to echo into the gap after it; word:2 for the second time it is said")
    p.add_argument("--beats", type=float, default=0.5, help="throw: time between echoes, in beats of the music")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("-m", "--message")
    p.add_argument("--force", action="store_true")
    p = command("captions", cmd_captions, "make captions from the placed voice")
    p.add_argument("--voice", help="only this placed voice (v001)")
    p.add_argument("--style", choices=["line", "word", "split"], default="line")
    p.add_argument("--punch", help="words to set full-frame, comma separated; word:2 means the second time it is said")
    p.add_argument("--accent", action="store_true", help="put a designed hit under each punch word, each one different")
    p.add_argument("--keep", action="store_true", help="add to existing captions instead of replacing them")
    p.add_argument("-m", "--message")
    p.add_argument("--force", action="store_true")
    p = command("draft", cmd_draft, "build a first assembly from a structure file")
    p.add_argument("structure")
    p.add_argument("--profile")
    p.add_argument("-m", "--message")
    p.add_argument("--force", action="store_true")
    command("validate", cmd_validate, "check the current cut for problems")
    command("plan", cmd_plan, "show how much a render would have to redo").add_argument("--proxy", action="store_true")
    p = command("render", cmd_render, "render the current cut")
    p.add_argument("--proxy", action="store_true", help="half-size preview")
    p.add_argument("--aspect", help="render a version in another shape: 9:16, 4:5, 1:1 (run `workprint reframe` first)")
    p.add_argument("--out")
    p.add_argument("--crf", type=int, help="x264 quality, lower is better and larger (default 20; 23 for --proxy)")
    p.add_argument("--jobs", type=int)
    p.add_argument("--json", action="store_true")
    p = command("intercut", cmd_intercut, "make a slot flicker back and forth to a second shot")
    p.add_argument("cut")
    p.add_argument("--shot")
    p.add_argument("--src")
    p.add_argument("--in", dest="start", type=float)
    p.add_argument("--every", type=int, default=2, help="frames per run before switching")
    p.add_argument("--from", dest="begin", type=float, default=0.0, help="seconds into the slot where the flicker starts")
    p.add_argument("--to", dest="end", type=float, help="seconds into the slot where it stops")
    p.add_argument("--off", action="store_true")
    p.add_argument("-m", "--message")
    p.add_argument("--force", action="store_true")
    p = command("reframe", cmd_reframe, "propose where each shot sits in a 9:16, 4:5 or 1:1 version, with a review sheet")
    p.add_argument("--aspect", required=True)
    p.add_argument("--slots", help="only these cut ids, comma separated (re-measures them)")
    p.add_argument("--redo", action="store_true", help="measure every slot again, replacing earlier choices")
    p.add_argument("-m", "--message")
    p.add_argument("--force", action="store_true")
    p = command("check", cmd_check, "measure a render against the cut, the music and the brief")
    p.add_argument("render", nargs="?")
    p.add_argument("--json", action="store_true")
    command("history", cmd_history, "list saved versions of the cut")
    p = command("diff", cmd_diff, "what changed between two versions")
    p.add_argument("a", nargs="?", type=int)
    p.add_argument("b", nargs="?", type=int)
    command("undo", cmd_undo, "go back one version (saved as a new version)")

    p = revision("replace", "put a different shot in a slot")
    p.add_argument("cut")
    p.add_argument("--shot")
    p.add_argument("--src")
    p.add_argument("--in", dest="start", type=float)
    p = revision("slip", "move the footage under a slot earlier/later")
    p.add_argument("cut")
    p.add_argument("delta", type=float)
    p = revision("roll", "move a cut point")
    p.add_argument("cut")
    p.add_argument("--by", type=float)
    p.add_argument("--to", type=float)
    p.add_argument("--snap", type=float, help="snap to the musical grid: 1 = beats, 2 = eighths, 0.25 = bars")
    p.add_argument("--on", choices=["kick", "snare", "hat"], help="land on the nearest drum hit of this kind")
    p.add_argument("--keep-in", action="store_true")
    p = revision("insert", "start a new slot at a time")
    p.add_argument("--at", type=float, required=True)
    p.add_argument("--shot")
    p.add_argument("--src")
    p.add_argument("--in", dest="start", type=float)
    revision("remove", "remove a cut, title, sound, caption or placed voice by id").add_argument("id")
    p = revision("swap", "exchange the footage of two slots")
    p.add_argument("a")
    p.add_argument("b")
    p = revision("shift", "ripple everything after a time")
    p.add_argument("--from", dest="start", type=float, required=True)
    p.add_argument("--by", type=float, required=True)
    p = revision("set", "set fields on a cut/title/sound/caption/voice id, or on look, music, audio, film")
    p.add_argument("target")
    p.add_argument("pairs", nargs="+", help="key=value (JSON or text); key= deletes")
    p = revision("new", "add a title, sound or caption: new title at=3 text=HELLO")
    p.add_argument("kind", choices=["title", "sound", "caption"])
    p.add_argument("pairs", nargs="+")

    p = command("profile", cmd_profile, "measure reference films into an editable style profile")
    p.add_argument("references", nargs="+")
    p.add_argument("-o", "--out", default="profile.json")
    p = command("export", cmd_export, "export the cut as an EDL and/or .otio (experimental)")
    p.add_argument("--edl")
    p.add_argument("--otio")
    command("clean", cmd_clean, "delete cached render chunks and mixes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except (ProjectError, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
