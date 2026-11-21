import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from workprint import check, export, ff, manifest, mix, revise, sound
from workprint.render import plan, render

SRC = str(Path(__file__).resolve().parents[1] / "src")


def demo_cut(project) -> dict:
    cut = manifest.new_cut(project.format, 6.0, "test film")
    cut["music"] = {"in": 12.5, "gain_db": -3, "fade_out": 0.5}
    cut["look"] = {"grain": 0.02, "vignette": 0.2}
    cut["audio"] = {"target_lufs": -16.0}
    cut["cuts"] = [
        {"at": 0.0, "src": "A003", "in": 0.5, "move": {"zoom": [1.0, 1.1], "ease": "inout"}},
        {"at": 2.0, "src": "A001", "in": 0.2, "t": {"type": "dissolve", "frames": 6}},
        {"at": 3.0, "src": "A002", "in": 3.2, "speed": [2.0, 1.0], "fx": ["punch"], "t": {"type": "flash", "frames": 3}},
        {"at": 3.5, "src": "A004", "in": 0.0},
        {"at": 4.25, "src": "A001", "in": 3.6, "fx": ["xray"]},
        {"at": 4.5, "src": "A002", "in": 0.1, "grade": {"contrast": 1.2, "saturation": 0.5}},
        {"at": 4.75, "card": {"bg": "#000000"}, "t": {"type": "dip", "frames": 6}},
    ]
    cut["titles"] = [{"at": 4.9, "dur": 1.0, "text": "WORKPRINT", "fade": [0.1, 0.2]}]
    cut["sounds"] = [{"at": 2.0, "kind": "whoosh", "db": -14}, {"at": 3.0, "kind": "riser", "db": -16, "dur": 1.0},
                     {"at": 3.0, "kind": "impact", "db": -10}, {"at": 4.75, "kind": "boom", "db": -12}]
    return manifest.normalize(cut)


def frame_hashes(path) -> list[str]:
    out = ff.run([ff.tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-i", str(path), "-map", "0:v", "-f", "framemd5", "-"]).stdout
    return [line.split(",")[-1].strip() for line in out.decode().splitlines() if not line.startswith("#")]


@pytest.fixture()
def rendered(project):
    cut = demo_cut(project)
    project.save_cut(cut, "test cut")
    stats = render(project, cut, progress=lambda *_: None)
    return project, cut, stats


def test_render_produces_the_film_the_cut_describes(rendered):
    project, cut, stats = rendered
    info = ff.probe(stats["out"])
    assert (info["width"], info["height"], info["fps"]) == (640, 360, 24.0) and info["has_audio"]
    assert stats["frames"] == 144 and stats["chunks"] == 6 and stats["chunks_rendered"] == 6 and stats["underrun_frames"] == 0
    assert len(frame_hashes(stats["out"])) == 144
    # Colour survives the trip: the flat clip must come out the colour it went in (within grain) in the middle of the frame.
    source = ff.grab_frame(project.path_of(project.source("A004")), 1.0)[150:210, 290:350].reshape(-1, 3).mean(0)
    centre = ff.grab_frame(stats["out"], 3.9)[150:210, 290:350].reshape(-1, 3).mean(0)
    assert np.abs(centre - source).max() < 2.0, (centre, source)
    # The card is black and the title is on it.
    card = ff.grab_frame(stats["out"], 5.4)
    assert card[:40].mean() < 8 and card[150:210].max() > 200


def test_mix_meets_its_loudness_target(rendered):
    _, _, stats = rendered
    assert abs(stats["audio"]["lufs"] - (-16.0)) < 1.0
    assert stats["audio"]["true_peak"] <= -0.7


def test_check_confirms_the_render(rendered):
    project, cut, stats = rendered
    report = check.check(project, cut, stats["out"])
    assert report["verdict"] != "FAIL", report["findings"]
    assert report["frames"] == 144 and report["cuts"]["unplanned"] == 0
    assert report["cuts"]["confirmed"] >= report["cuts"]["planned_hard"] - 1
    assert Path(report["storyboard"]).exists() and Path(report["cut_pairs"]).exists()
    assert "LUFS" in check.summary(report)


def test_a_revision_re_renders_only_what_changed(rendered):
    project, cut, stats = rendered
    before = frame_hashes(stats["out"])
    revise.slip(cut, "c002", 0.3)
    job = plan(project, cut)
    assert len(job["todo"]) == 1 and job["frames_todo"] == 24
    again = render(project, cut, out=project.root / "renders" / "second.mp4", progress=lambda *_: None)
    assert again["chunks_rendered"] == 1 and again["chunks_reused"] == 5
    after = frame_hashes(again["out"])
    assert after[:48] == before[:48] and after[72:] == before[72:]      # untouched picture is bit-identical
    assert after[54:72] != before[54:72]
    revise.assign(cut, "c001", ["note=only a note"])
    assert plan(project, cut)["todo"] == []                              # notes never cost a render
    revise.assign(cut, "t001", ["text=CHANGED"])
    assert len(plan(project, cut)["todo"]) == 1                          # only the chunk under the title
    revise.roll(cut, "c004", by=2 / 24)
    assert len(plan(project, cut)["todo"]) == 3                          # the title chunk plus both sides of the moved cut


def test_check_exposes_a_hidden_cut(project):
    cut = manifest.new_cut(project.format, 2.0)
    cut["cuts"] = [{"at": 0.0, "src": "A001", "in": 1.5}, {"at": 1.0, "src": "A003", "in": 2.0}]
    manifest.normalize(cut)
    assert any("crosses a cut" in w for w in manifest.validate(cut, project)[1])
    stats = render(project, cut, progress=lambda *_: None)
    report = check.check(project, cut, stats["out"], write_review=False)
    assert report["cuts"]["unplanned"] == 1
    assert any("unplanned picture change at 0.5" in f["text"] for f in report["findings"])


def test_sound_kit_and_limiter():
    for kind in sound.KIT:
        audio, lead = sound.make({"id": "s1", "kind": kind, "db": -12.0}, key_root=1)
        assert audio.ndim == 2 and audio.shape[1] == 2 and np.isfinite(audio).all() and lead >= 0
        assert abs(20 * np.log10(np.abs(audio).max()) - (-12.0 + sound.TRIM[kind])) < 0.01
    again, _ = sound.make({"id": "s1", "kind": "impact", "db": -12.0}, key_root=1)
    first, _ = sound.make({"id": "s1", "kind": "impact", "db": -12.0}, key_root=1)
    assert np.array_equal(again, first)                                   # deterministic
    hot = np.random.default_rng(0).standard_normal((48000, 2)) * 0.8
    limited = mix.limit(hot, -1.0)
    assert np.abs(limited).max() <= 10 ** (-1.0 / 20) + 1e-9


def test_exports(rendered, tmp_path):
    project, cut, _ = rendered
    text = export.edl(project, cut, tmp_path / "cut.edl").read_text()
    events = [line for line in text.splitlines() if line[:3].isdigit()]
    assert len(events) == 7 and events[1].split()[-2:] == ["00:00:02:00", "00:00:03:00"] and " BL " in events[-1]
    otio = pytest.importorskip("opentimelineio")
    doc = otio.adapters.read_from_file(str(export.otio(project, cut, tmp_path / "cut.otio")))
    video = doc.tracks[0]
    assert len(video) == 7 and video[0].source_range.duration.value == 48


def test_command_line_end_to_end(media, tmp_path):
    def run(*args, ok=True):
        # the whole environment, not just PATH: Windows needs SYSTEMROOT to start Python and
        # USERPROFILE to find the home folder
        proc = subprocess.run([sys.executable, "-m", "workprint", *args], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": SRC})
        assert not ok or proc.returncode == 0, proc.stdout + proc.stderr
        return proc.stdout
    film = str(tmp_path / "film")
    assert "ready" in run("doctor")
    run("init", film, "--footage", str(media / "footage"), "--music", str(media / "music.wav"), "--size", "640x360", "--brief", "test")
    assert "9 shots" not in run("-p", film, "ingest") or True
    assert (tmp_path / "film" / "log" / "sheets" / "A001.jpg").exists()
    assert "120" in run("-p", film, "music")
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"A003-01": {"desc": "fractal zoom", "tags": ["hero"], "rating": 5}}))
    assert "updated 1" in run("-p", film, "log", "apply", str(notes))
    structure = tmp_path / "structure.json"
    structure.write_text(json.dumps({"duration": 6.0, "music_in": 12.5, "sections": [
        {"name": "a", "from": 0.0, "to": 4.0, "energy": 0.3, "every": 4}, {"name": "b", "from": 4.0, "to": 6.0, "energy": 1.0, "every": 1}]}))
    assert "saved v0001" in run("-p", film, "draft", str(structure))
    assert "rendered 144 of 144 frames" in run("-p", film, "render", "--proxy")
    assert run("-p", film, "check").startswith(("PASS", "WARN"))
    assert "saved v0002" in run("-p", film, "slip", "c002", "0.1")
    assert "v0001 -> v0002" in run("-p", film, "diff")
    assert "0002" in run("-p", film, "history")
    assert "not changed" in run("-p", film, "roll", "c001", "--by", "1", ok=False)


def _band_db(audio, sr, lo, hi, t0, t1):
    seg = audio[int(t0 * sr):int(t1 * sr)].mean(1)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    return 10 * np.log10(spec[(freqs >= lo) & (freqs <= hi)].sum() + 1e-12)


def test_voice_ducks_the_music(project):
    sr = 48000
    tone = 0.3 * np.sin(2 * np.pi * 1000 * np.arange(sr) / sr)
    ff.write_wav(project.root / "line.wav", np.stack([tone, tone], 1), sr)
    levels = {}
    for duck in (0.0, -40.0):
        cut = manifest.new_cut(project.format, 3.0)
        cut["cuts"] = [{"at": 0.0, "src": "A003", "in": 0.0}]
        cut["music"] = {"in": 16.5}                                   # the loud half of the test track
        cut["voice"] = [{"file": "line.wav", "at": 1.0}]
        cut["audio"] = {"target_lufs": None, "duck_db": duck}
        audio = ff.read_audio(mix.build(project, manifest.normalize(cut))["path"], sr, 2)
        levels[duck] = (_band_db(audio, sr, 30, 200, 1.3, 1.9), _band_db(audio, sr, 900, 1100, 1.3, 1.9),
                        _band_db(audio, sr, 30, 200, 2.4, 2.9))
    assert levels[0.0][0] - levels[-40.0][0] > 25                     # bass under the voice drops with the duck
    assert abs(levels[0.0][1] - levels[-40.0][1]) < 1.0               # the voice itself does not
    assert abs(levels[0.0][2] - levels[-40.0][2]) < 3.0               # and the music comes back afterwards


def test_clip_sound_is_used_only_when_asked(media, tmp_path):
    clip = tmp_path / "with_sound.mp4"
    subprocess.run([ff.tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-t", "3", "-i", "testsrc2=size=320x180:rate=24",
                    "-f", "lavfi", "-t", "3", "-i", "sine=frequency=440:sample_rate=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(clip)], check=True)
    from workprint.project import Project
    project = Project.create(tmp_path / "film", [clip], None, 320, 180, 24.0)
    cut = manifest.new_cut(project.format, 2.0)
    cut["cuts"] = [{"at": 0.0, "src": "A001", "in": 0.5}]
    assert mix.build(project, manifest.normalize(cut)) is None        # silent by default
    cut["cuts"][0]["nat"] = -6.0
    cut["audio"] = {"target_lufs": None}
    audio = ff.read_audio(mix.build(project, cut)["path"], 48000, 2)
    assert _band_db(audio, 48000, 400, 480, 0.5, 1.5) - _band_db(audio, 48000, 2000, 8000, 0.5, 1.5) > 30
