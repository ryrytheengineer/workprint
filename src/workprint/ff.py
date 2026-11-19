"""Thin wrappers around the ffmpeg and ffprobe command-line tools.

Workprint never links against FFmpeg. It runs the user's own ``ffmpeg`` and
``ffprobe`` binaries as subprocesses and exchanges raw frames and PCM audio
over pipes. Everything that touches a media file goes through this module.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np


class FFError(RuntimeError):
    """An ffmpeg/ffprobe invocation failed."""


def tool(name: str) -> str:
    """Locate ``ffmpeg`` or ``ffprobe`` (override with WORKPRINT_FFMPEG / WORKPRINT_FFPROBE)."""
    path = os.environ.get(f"WORKPRINT_{name.upper()}") or shutil.which(name)
    if not path:
        raise FFError(f"{name} was not found on PATH. Run `workprint doctor` for install steps.")
    return path


def run(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, input=stdin, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise FFError(f"{Path(args[0]).name} failed: " + " | ".join(tail))
    return proc


def fps_arg(fps: float) -> str:
    """Exact rational for common broadcast rates (23.976 -> 24000/1001)."""
    frac = Fraction(fps).limit_denominator(1001)
    return f"{frac.numerator}/{frac.denominator}"


def _ratio(text: str | None) -> float:
    if not text or text in ("0/0", "N/A"):
        return 0.0
    num, _, den = text.partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


def probe(path: str | Path) -> dict:
    """Return the facts Workprint needs about a media file."""
    out = run([tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    data = json.loads(out.stdout)
    fmt = data.get("format", {})
    info: dict = {"duration": float(fmt.get("duration") or 0.0), "has_video": False, "has_audio": False}
    for st in data.get("streams", []):
        if st.get("codec_type") == "video" and not st.get("disposition", {}).get("attached_pic") and not info["has_video"]:
            w, h = int(st["width"]), int(st["height"])
            rot = 0
            for sd in st.get("side_data_list", []):
                if "rotation" in sd:
                    rot = int(round(float(sd["rotation"])))
            if abs(rot) % 180 == 90:
                w, h = h, w
            fps = _ratio(st.get("avg_frame_rate")) or _ratio(st.get("r_frame_rate"))
            info.update(
                has_video=True, width=w, height=h, fps=round(fps, 4), codec=st.get("codec_name"),
                pix_fmt=st.get("pix_fmt"), color_space=st.get("color_space"), color_transfer=st.get("color_transfer"),
                video_duration=float(st.get("duration") or info["duration"]),
            )
        elif st.get("codec_type") == "audio" and not info["has_audio"]:
            info.update(has_audio=True, sample_rate=int(st.get("sample_rate") or 0), channels=int(st.get("channels") or 0))
    return info


def color_matrix(info: dict) -> str:
    """Matrix to use when converting a source to RGB. Untagged HD is treated as BT.709."""
    tagged = (info.get("color_space") or "").lower()
    if tagged in ("bt470bg", "smpte170m"):
        return "bt601"
    if tagged in ("bt709", "bt2020nc", "bt2020c"):
        return "bt709"
    return "bt709" if info.get("height", 0) >= 720 else "bt601"


class FrameReader:
    """Sequential BGR frames from a source, already resampled to the output frame rate.

    ``time_map`` is an optional ffmpeg ``setpts`` expression implementing speed changes.
    ``crop`` is (w, h, x, y) applied after scaling.
    """

    def __init__(self, path, start: float, fps: float, scale: tuple[int, int], crop: tuple[int, int, int, int] | None = None,
                 matrix: str = "bt709", time_map: str | None = None, scaler: str = "lanczos"):
        sw, sh = scale
        self.size = (crop[0], crop[1]) if crop else (sw, sh)
        chain = []
        if time_map:
            chain.append(f"setpts={time_map}")
        chain.append(f"fps={fps_arg(fps)}")
        # accurate_rnd + full_chroma_int: without them swscale's fast path shifts greys by up to two code values
        chain.append(f"scale={sw}:{sh}:flags={scaler}+accurate_rnd+full_chroma_int:in_color_matrix={matrix}")
        if crop:
            chain.append("crop={}:{}:{}:{}".format(*crop))
        chain.append("format=bgr24")
        args = [tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-ss", f"{max(0.0, start):.6f}", "-i", str(path),
                "-an", "-sn", "-vf", ",".join(chain), "-f", "rawvideo", "-"]
        self._bytes = self.size[0] * self.size[1] * 3
        self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self._bytes)
        self.frames_read = 0

    def read(self) -> np.ndarray | None:
        buf = self._proc.stdout.read(self._bytes)
        if len(buf) < self._bytes:
            return None
        self.frames_read += 1
        return np.frombuffer(buf, np.uint8).reshape(self.size[1], self.size[0], 3)

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.stdout.close()
        self._proc.wait()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FrameWriter:
    """Encode BGR frames to H.264 with BT.709 tagging. One instance per render chunk."""

    def __init__(self, path, size: tuple[int, int], fps: float, crf: int = 20, preset: str = "medium"):
        self.path = Path(path)
        self._tmp = self.path.with_suffix(".part.mp4")
        self._err = tempfile.TemporaryFile()
        args = [tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s", f"{size[0]}x{size[1]}", "-r", fps_arg(fps), "-i", "-",
                "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p",
                "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-bf", "2", "-g", "48",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                str(self._tmp)]
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=self._err)

    def write(self, frame: np.ndarray) -> None:
        try:
            self._proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        except BrokenPipeError:
            self.close()

    def close(self) -> None:
        if self._proc.stdin and not self._proc.stdin.closed:
            self._proc.stdin.close()
        code = self._proc.wait()
        self._err.seek(0)
        err = self._err.read().decode("utf-8", "replace").strip()
        self._err.close()
        if code != 0:
            self._tmp.unlink(missing_ok=True)
            raise FFError("encoder failed: " + " | ".join(err.splitlines()[-4:]))
        os.replace(self._tmp, self.path)


def read_audio(path, sr: int = 48000, channels: int = 2, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    """Decode audio to float32, shape (samples, channels). Returns silence-free empty array if no audio."""
    args = [tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-ss", f"{max(0.0, start):.6f}", "-i", str(path)]
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    args += ["-vn", "-sn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    raw = run(args).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, channels).copy()


def write_wav(path, data: np.ndarray, sr: int = 48000) -> None:
    """Write float audio as 24-bit PCM WAV."""
    data = np.ascontiguousarray(np.clip(data, -1.0, 1.0), dtype=np.float32)
    channels = 1 if data.ndim == 1 else data.shape[1]
    run([tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(channels),
         "-i", "-", "-c:a", "pcm_s24le", str(path)], stdin=data.tobytes())


def loudness(path) -> dict:
    """Integrated loudness (LUFS), loudness range (LU) and true peak (dBTP) per EBU R128, measured by ffmpeg."""
    proc = subprocess.run([tool("ffmpeg"), "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=peak=true",
                           "-f", "null", "-"], capture_output=True)
    text = proc.stderr.decode("utf-8", "replace")
    summary = text[text.rfind("Summary:"):] if "Summary:" in text else ""

    def grab(pattern):
        m = re.search(pattern, summary)
        return float(m.group(1)) if m else None

    return {"lufs": grab(r"I:\s+(-?[\d.]+) LUFS"), "lra": grab(r"LRA:\s+(-?[\d.]+) LU"), "true_peak": grab(r"Peak:\s+(-?[\d.]+) dBFS")}


def grab_frame(path, t: float, width: int | None = None) -> np.ndarray:
    """One BGR frame at source time ``t`` (seconds)."""
    info = probe(path)
    w, h = info["width"], info["height"]
    if width and width < w:
        h = int(round(h * width / w / 2)) * 2
        w = width
    with FrameReader(path, t, info["fps"] or 24.0, (w, h), matrix=color_matrix(info), scaler="bicubic") as reader:
        frame = reader.read()
    if frame is None:
        raise FFError(f"no frame at {t:.3f}s in {path}")
    return frame.copy()


def concat_copy(parts: list[Path], out: Path, audio: Path | None = None) -> None:
    """Join chunk files without re-encoding picture; optionally mux an audio file as AAC."""
    listing = out.with_suffix(".concat.txt")
    listing.write_text("".join("file '{}'\n".format(str(p).replace("'", "'\\''")) for p in parts), encoding="utf-8")
    args = [tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
    if audio:
        args += ["-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "320k"]
    args += ["-c:v", "copy", "-movflags", "+faststart", str(out)]
    try:
        run(args)
    finally:
        listing.unlink(missing_ok=True)
