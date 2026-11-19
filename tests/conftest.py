"""Synthetic media for the tests: footage with known cuts and music with a known grid.

Everything is generated with ffmpeg's built-in test sources and NumPy, so the suite
needs no media files and the expected answers are exact.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workprint import ff  # noqa: E402
from workprint.project import Project  # noqa: E402

SIZE, RATE = "640x360", 30
# (source, seconds) per shot; cuts fall at the cumulative sums.
CLIPS = {
    "a_patterns.mp4": [("testsrc2", 2.0), ("mandelbrot", 1.5), ("gradients=speed=0.08:seed=7", 2.5)],
    "b_bars.mp4": [("smptebars", 1.2), ("rgbtestsrc", 1.8), ("testsrc", 3.0)],
    "c_long.mp4": [("mandelbrot=start_scale=1.5", 6.0)],
    "d_flat.mp4": [("color=c=0x336699", 3.0)],
}
BPM, LEAD, BARS, DROP_BAR = 120.0, 0.5, 16, 9


def _make_clip(path: Path, shots):
    args = [ff.tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-y"]
    for source, seconds in shots:
        sep = ":" if "=" in source else "="
        args += ["-f", "lavfi", "-t", str(seconds), "-i", f"{source}{sep}size={SIZE}:rate={RATE}"]
    labels = "".join(f"[{i}:v]" for i in range(len(shots)))
    args += ["-filter_complex", f"{labels}concat=n={len(shots)}:v=1:a=0,format=yuv420p", "-c:v", "libx264", "-crf", "12",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", str(path)]
    subprocess.run(args, check=True)


def _make_music(path: Path):
    """Quiet hats for eight bars, then kick and bass: a clean grid and an unmistakable drop."""
    sr = 48000
    beat = 60.0 / BPM
    total = LEAD + BARS * 4 * beat + 1.0
    t = np.arange(int(total * sr)) / sr
    out = np.zeros_like(t)
    rng = np.random.default_rng(3)
    for k in range(BARS * 4):
        at = LEAD + k * beat
        i = int(at * sr)
        loud = k >= (DROP_BAR - 1) * 4
        n = int(0.05 * sr)
        hat = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.008 * sr)) * (0.10 if not loud else 0.16)
        out[i:i + n] += hat
        if loud:
            n = int(0.30 * sr)
            tt = np.arange(n) / sr
            accent = 1.0 if k % 4 == 0 else 0.65
            out[i:i + n] += np.sin(2 * np.pi * (50 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt / 0.09) * 0.8 * accent
            out[i:i + int(beat * sr)] += 0.2 * np.sin(2 * np.pi * 55 * np.arange(int(beat * sr)) / sr)
    ff.write_wav(path, np.stack([out, out], 1) * 0.8, sr)


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("media")
    (root / "footage").mkdir()
    for name, shots in CLIPS.items():
        _make_clip(root / "footage" / name, shots)
    _make_music(root / "music.wav")
    return root


@pytest.fixture(scope="session")
def analysed(media, tmp_path_factory) -> Path:
    """A project with footage ingested and music analysed, shared read-only by tests."""
    from workprint import music, shots
    from workprint.project import write_json
    root = tmp_path_factory.mktemp("project")
    project = Project.create(root / "film", [media / "footage"], media / "music.wav", 640, 360, 24.0)
    shots.ingest(project, progress=lambda *_: None)
    write_json(project.log_dir / "music.json", music.analyze(project.music_path()))
    return project.root


@pytest.fixture()
def project(analysed, tmp_path) -> Project:
    """A private copy of the analysed project (sources stay shared and untouched)."""
    import shutil
    target = tmp_path / "film"
    shutil.copytree(analysed, target)
    return Project(target)
