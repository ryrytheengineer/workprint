"""The renderer: turns a cut into picture, chunk by chunk.

Frames are composited in Python (NumPy/OpenCV) and piped to ffmpeg for encoding.
The film is rendered as independent *chunks* (see ``manifest.chunk_plan``); each
chunk is stored under a key derived from everything that affects its pixels.
A revision therefore re-renders only the chunks whose key changed, and the final
film is assembled by joining chunk files without re-encoding, so untouched parts
of the picture are bit-identical from one version to the next.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from . import ff
from .look import Finish, Grade, apply_fx, ease, hex_bgr, resolve_look
from .manifest import chunk_plan, source_span, speed_pair, timeline, transition_of, validate
from .titles import Title, opacity_at, schedule

RENDER_REV = 1  # bump when a change to this module alters pixels: invalidates every cached chunk


class RenderError(RuntimeError):
    pass


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _pair(value, default: float) -> tuple[float, float]:
    if value is None:
        return default, default
    if isinstance(value, (list, tuple)):
        return float(value[0]), float(value[1])
    return float(value), float(value)


class Context:
    """Everything needed to render any chunk of one cut at one output size."""

    def __init__(self, project, cut: dict, scale: float = 1.0, crf: int = 20, preset: str = "medium"):
        self.project, self.cut = project, cut
        fmt = cut["format"]
        self.fps = float(fmt["fps"])
        self.W, self.H = _even(fmt["width"] * scale), _even(fmt["height"] * scale)
        self.crf, self.preset = crf, preset
        self.slots = timeline(cut)
        self.chunks = chunk_plan(cut)
        self.title_plan = schedule(cut.get("titles"), self.fps)
        self._finish = None
        self._titles = None

    @property
    def finish(self) -> Finish:
        if self._finish is None:
            self._finish = Finish(self.cut.get("look"), self.W, self.H)
        return self._finish

    @property
    def titles(self) -> list[tuple[dict, Title]]:
        if self._titles is None:
            self._titles = [(item, Title(item["spec"], self.W, self.H)) for item in self.title_plan]
        return self._titles

    # ---- cache keys ----------------------------------------------------------------------------
    def _core(self, i: int) -> dict:
        entry = self.slots[i]["cut"]
        spec = {"n": self.slots[i]["f1"] - self.slots[i]["f0"], "grade": entry.get("grade"), "fx": entry.get("fx")}
        if "card" in entry:
            spec["card"] = entry["card"]
        else:
            spec["sig"] = self.project.source(entry["src"])["sig"]
            spec.update({k: entry.get(k) for k in ("in", "speed", "move", "fit", "focus", "freeze")})
        return spec

    def slot_spec(self, i: int) -> dict:
        spec = dict(self._core(i))
        spec["t"] = transition_of(self.slots[i]["cut"])
        if spec["t"]["type"] == "dissolve":
            spec["prev"] = self._core(i - 1)
        if i + 1 < len(self.slots):
            after = transition_of(self.slots[i + 1]["cut"])
            if after["type"] == "dip":
                spec["out"] = after
        return spec

    def chunk_key(self, chunk: dict) -> str:
        f0, f1 = chunk["f0"], chunk["f1"]
        titles = [[{k: v for k, v in item["spec"].items() if k not in ("id", "at", "note")},
                   item["f0"] - f0, item["f1"] - f0, item["fade_in"], item["fade_out"]]
                  for item in self.title_plan if item["f0"] < f1 and item["f1"] > f0]
        payload = {"rev": RENDER_REV, "size": [self.W, self.H], "fps": self.fps, "crf": self.crf, "preset": self.preset,
                   "look": resolve_look(self.cut.get("look")), "slots": [self.slot_spec(i) for i in chunk["slots"]], "titles": titles}
        return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:20]

    def chunk_path(self, chunk: dict) -> Path:
        folder = self.project.cache_dir / "chunks"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self.chunk_key(chunk)}.mp4"


class SlotPlayer:
    """Frames of one slot, in order, after reframing, camera move, grade and effects.

    ``start_local`` is 0 for the slot itself, or the slot's own length to keep playing
    past its out-point (the outgoing side of a dissolve).
    """

    def __init__(self, ctx: Context, i: int, start_local: int = 0):
        slot = ctx.slots[i]
        entry = self.entry = slot["cut"]
        self.n = slot["f1"] - slot["f0"]
        self.local = start_local
        self.W, self.H = ctx.W, ctx.H
        self.grade = Grade(entry.get("grade"))
        self.fx = entry.get("fx") or []
        self.underrun = 0
        self.last = None
        self.reader = None
        self.card = None
        if "card" in entry:
            self.card = np.full((self.H, self.W, 3), hex_bgr(entry["card"].get("bg", "#000000")), np.uint8)
            return
        source = ctx.project.source(entry["src"])
        move = entry.get("move") or {}
        self.zoom = tuple(max(1.0, z) for z in _pair(move.get("zoom"), 1.0))
        self.cx, self.cy = _pair(move.get("x"), 0.5), _pair(move.get("y"), 0.5)
        self.ease = move.get("ease", "linear")
        self.freeze = bool(entry.get("freeze"))
        sw, sh = source["width"], source["height"]
        self.contain = entry.get("fit") == "contain"
        if self.contain:
            k = min(self.W / sw, self.H / sh)
            scale, crop = (_even(sw * k), _even(sh * k)), None
            self.frame_w, self.frame_h = self.W, self.H
        else:
            k = max(self.W / sw, self.H / sh)
            zmax = max(self.zoom)
            dec = k if k >= 1.0 else min(k * zmax, 1.0)  # decode a little larger so a push-in stays sharp
            q = dec / k
            dw, dh = _even(sw * dec), _even(sh * dec)
            cw, ch = min(dw, _even(self.W * q)), min(dh, _even(self.H * q))
            fx_, fy_ = entry.get("focus") or (0.5, 0.5)
            scale, crop = (dw, dh), (cw, ch, int((dw - cw) * fx_), int((dh - ch) * fy_))
            self.frame_w, self.frame_h = cw, ch
        s0, s1 = speed_pair(entry)
        a, b = source_span(entry, self.n, ctx.fps)
        if start_local == 0:
            start = a
            if self.freeze or s0 == s1 == 1.0:
                time_map = None
            elif s0 == s1:
                time_map = f"(PTS-STARTPTS)/{s0!r}"
            else:  # linear speed ramp: invert source_time(t) = s0*t + accel*t^2/2
                accel = (s1 - s0) / (self.n / ctx.fps)
                time_map = f"((-{s0!r}+sqrt({s0 * s0!r}+2*({accel!r})*(PTS-STARTPTS)*TB))/({accel!r}))/TB"
        else:
            start, time_map = b, (None if s1 == 1.0 else f"(PTS-STARTPTS)/{s1!r}")
        self.reader = ff.FrameReader(ctx.project.path_of(source), start, ctx.fps, scale, crop, source.get("matrix", "bt709"), time_map)

    def _reframe(self, raw: np.ndarray, local: int) -> np.ndarray:
        if self.contain:
            canvas = np.zeros((self.H, self.W, 3), np.uint8)
            y, x = (self.H - raw.shape[0]) // 2, (self.W - raw.shape[1]) // 2
            canvas[y:y + raw.shape[0], x:x + raw.shape[1]] = raw
            raw = canvas
        p = ease(local / max(1, self.n - 1), self.ease)
        z = self.zoom[0] + (self.zoom[1] - self.zoom[0]) * p
        s = z * self.W / self.frame_w
        win_w, win_h = self.W / s, self.H / s
        cx = self.cx[0] + (self.cx[1] - self.cx[0]) * p
        cy = self.cy[0] + (self.cy[1] - self.cy[0]) * p
        x0 = min(max(cx * self.frame_w - win_w / 2, 0.0), self.frame_w - win_w)
        y0 = min(max(cy * self.frame_h - win_h / 2, 0.0), self.frame_h - win_h)
        if abs(s - 1.0) < 1e-6 and abs(x0 - round(x0)) < 1e-6 and abs(y0 - round(y0)) < 1e-6:
            x0, y0 = int(round(x0)), int(round(y0))
            return raw[y0:y0 + self.H, x0:x0 + self.W]
        m = np.float32([[s, 0, -s * x0], [0, s, -s * y0]])
        return cv2.warpAffine(raw, m, (self.W, self.H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    def next(self) -> np.ndarray:
        local = self.local
        self.local += 1
        if self.card is not None:
            frame = self.card
        else:
            raw = self.last if (self.freeze and self.last is not None) else self.reader.read()
            if raw is None:  # the source ran out: hold the last frame and report it
                self.underrun += 1
                raw = self.last if self.last is not None else np.zeros((self.frame_h, self.frame_w, 3), np.uint8)
            self.last = raw
            frame = self._reframe(raw, min(local, self.n - 1))
        return apply_fx(self.grade.apply(frame), self.fx, local, self.n)

    def close(self) -> None:
        if self.reader:
            self.reader.close()


def _toward(frame: np.ndarray, color: str, amount: float) -> np.ndarray:
    solid = np.empty_like(frame)
    solid[:] = hex_bgr(color)
    return cv2.addWeighted(frame, 1.0 - amount, solid, amount, 0)


def render_chunk(ctx: Context, index: int) -> dict:
    """Render one chunk to its cache file. Returns frame and underrun counts."""
    chunk = ctx.chunks[index]
    path = ctx.chunk_path(chunk)
    writer = ff.FrameWriter(path, (ctx.W, ctx.H), ctx.fps, ctx.crf, ctx.preset)
    frames = underrun = 0
    try:
        for i in chunk["slots"]:
            slot = ctx.slots[i]
            n = slot["f1"] - slot["f0"]
            trans = transition_of(slot["cut"])
            after = transition_of(ctx.slots[i + 1]["cut"]) if i + 1 < len(ctx.slots) else {"type": "cut", "frames": 0}
            fade_out = after["frames"] // 2 if after["type"] == "dip" else 0
            player = SlotPlayer(ctx, i)
            outgoing = SlotPlayer(ctx, i - 1, ctx.slots[i - 1]["f1"] - ctx.slots[i - 1]["f0"]) if trans["type"] == "dissolve" else None
            try:
                for local in range(n):
                    frame = player.next()
                    if outgoing is not None and local < trans["frames"]:
                        frame = cv2.addWeighted(outgoing.next(), 1.0 - (local + 1) / (trans["frames"] + 1), frame,
                                                (local + 1) / (trans["frames"] + 1), 0)
                    elif trans["type"] == "dip":
                        fade_in = trans["frames"] - trans["frames"] // 2
                        if local < fade_in:
                            frame = _toward(frame, trans.get("color", "#000000"), 1.0 - (local + 1) / (fade_in + 1))
                    elif trans["type"] == "flash" and local < trans["frames"]:
                        frame = _toward(frame, trans.get("color", "#ffffff"), 0.9 * (1.0 - local / trans["frames"]) ** 1.5)
                    if fade_out and local >= n - fade_out:
                        frame = _toward(frame, after.get("color", "#000000"), (local - (n - fade_out) + 1) / (fade_out + 1))
                    frame = ctx.finish.apply(frame, frames)
                    absolute = slot["f0"] + local
                    for item, title in ctx.titles:
                        alpha = opacity_at(item, absolute)
                        if alpha > 0:
                            if not frame.flags.writeable:
                                frame = frame.copy()
                            title.draw(frame, alpha)
                    writer.write(frame)
                    frames += 1
                underrun += player.underrun
            finally:
                player.close()
                if outgoing is not None:
                    outgoing.close()
    finally:
        writer.close()
    return {"index": index, "frames": frames, "underrun": underrun}


def _worker(args) -> dict:
    from .project import Project
    root, cut, index, scale, crf, preset = args
    return render_chunk(Context(Project(root), cut, scale, crf, preset), index)


def plan(project, cut: dict, scale: float = 1.0, crf: int = 20, preset: str = "medium") -> dict:
    """Which chunks a render would reuse and which it would have to render."""
    ctx = Context(project, cut, scale, crf, preset)
    paths = [ctx.chunk_path(chunk) for chunk in ctx.chunks]
    todo = [i for i, p in enumerate(paths) if not p.exists()]
    return {"ctx": ctx, "paths": paths, "todo": todo,
            "frames_total": sum(c["f1"] - c["f0"] for c in ctx.chunks),
            "frames_todo": sum(ctx.chunks[i]["f1"] - ctx.chunks[i]["f0"] for i in todo)}


def render(project, cut: dict, out: Path | None = None, scale: float = 1.0, crf: int = 20, preset: str = "medium",
           jobs: int | None = None, progress=print) -> dict:
    """Render the cut to an MP4. Returns what was rendered, what was reused, and how long it took."""
    from . import mix  # imported here so picture-only tools do not need the audio stack loaded
    errors, warnings = validate(cut, project)
    if errors:
        raise RenderError("the cut does not validate:\n  " + "\n  ".join(errors))
    started = time.time()
    job = plan(project, cut, scale, crf, preset)
    ctx, todo = job["ctx"], job["todo"]
    jobs = jobs or max(1, min(4, (os.cpu_count() or 2) // 2))
    underrun = 0
    if todo:
        progress(f"rendering {len(todo)} of {len(ctx.chunks)} chunks ({job['frames_todo']} of {job['frames_total']} frames)")
        if jobs > 1 and len(todo) > 1:
            work = [(str(project.root), cut, i, scale, crf, preset) for i in todo]
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                for result in pool.map(_worker, work):
                    underrun += result["underrun"]
        else:
            for i in todo:
                underrun += render_chunk(ctx, i)["underrun"]
    else:
        progress(f"picture unchanged: all {len(ctx.chunks)} chunks reused")
    picture_seconds = time.time() - started
    audio = mix.build(project, cut)
    if out is None:
        suffix = "" if scale == 1.0 else "-proxy"
        out = project.root / "renders" / f"cut-v{project.version():04d}{suffix}.mp4"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ff.concat_copy(job["paths"], out, audio["path"] if audio else None)
    return {"out": str(out), "chunks": len(ctx.chunks), "chunks_rendered": len(todo), "chunks_reused": len(ctx.chunks) - len(todo),
            "frames": job["frames_total"], "frames_rendered": job["frames_todo"], "underrun_frames": underrun,
            "picture_seconds": round(picture_seconds, 2), "seconds": round(time.time() - started, 2),
            "audio": {k: v for k, v in (audio or {}).items() if k != "path"} or None, "warnings": warnings}
