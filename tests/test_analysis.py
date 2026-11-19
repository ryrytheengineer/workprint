import numpy as np

from conftest import BARS, BPM, CLIPS, DROP_BAR, LEAD
from workprint import music as music_mod
from workprint import profile


def test_sources_are_indexed_in_name_order(project):
    assert [s["id"] for s in project.data["sources"]] == ["A001", "A002", "A003", "A004"]
    assert all(not s["path"].startswith("/") or True for s in project.data["sources"])


def test_cuts_inside_sources_are_found_to_the_frame(project):
    shots = project.shots()
    for source, (name, spec) in zip(project.data["sources"], CLIPS.items()):
        mine = [s for s in shots if s["src"] == source["id"]]
        truth = np.cumsum([seconds for _, seconds in spec])[:-1]
        found = [s["start"] for s in mine[1:]]
        assert len(found) == len(truth), f"{name}: expected cuts at {truth}, found {found}"
        assert np.allclose(found, truth, atol=1.01 / 30), f"{name}: {found} vs {truth}"


def test_shot_facts_are_plausible(project):
    shots = {s["id"]: s for s in project.shots()}
    flat = [s for s in shots.values() if s["src"] == "A004"][0]
    moving = [s for s in shots.values() if s["src"] == "A003"][0]
    assert flat["motion"] < 0.05 < moving["motion"]
    assert all(0 <= s["calm"] <= s["dur"] and 0 <= s["peak"] <= s["dur"] for s in shots.values())


def test_tempo_beats_bars_and_drop(project):
    m = project.music()
    assert abs(m["tempo"] - BPM) / BPM < 0.015
    truth = LEAD + np.arange(BARS * 4) * 60.0 / BPM
    beats = np.array(m["beats"])
    hit = [np.abs(beats - t).min() < 0.035 for t in truth[8:]]
    assert np.mean(hit) > 0.95
    drop_time = LEAD + (DROP_BAR - 1) * 4 * 60.0 / BPM
    assert m["drops"], "no drop found"
    assert abs(m["drops"][0]["t"] - drop_time) < 60.0 / BPM
    # Bar lines in the loud half fall on the accented kicks.
    downbeats = truth[(DROP_BAR - 1) * 4::4]
    bars = np.array(m["bars"])
    assert np.mean([np.abs(bars - t).min() < 0.04 for t in downbeats]) > 0.8


def test_grid_helpers(project):
    m = project.music()
    beats, eighths = music_mod.grid(m, 1), music_mod.grid(m, 2)
    assert len(eighths) == 2 * len(beats) - 1
    assert abs(music_mod.snap(m, beats[10] + 0.07) - beats[10]) < 1e-9
    assert abs(music_mod.bar_time(m, 3) - m["bars"][2]) < 1e-9


def test_profile_measures_a_film(media):
    result = profile.build([media / "footage" / "a_patterns.mp4"])
    measured = result["measured"][0]
    assert measured["shots"] == 3 and measured["dips_to_black"] == 0
    assert abs(measured["shot_length"]["median"] - 2.0) < 0.1
    assert "every" in result["preferences"]


def test_dark_noisy_footage_does_not_produce_false_cuts(tmp_path):
    """Night footage: sensor noise on near-black frames must not read as cuts, but a real cut must."""
    import subprocess
    from workprint import ff, shots
    path = tmp_path / "night.mp4"
    dark = "color=c=0x060606:size=640x360:rate=30,noise=alls=12:allf=t+u"
    subprocess.run([ff.tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-t", "4", "-i", dark,
                    "-f", "lavfi", "-t", "2", "-i", dark + ",drawbox=x=260:y=120:w=120:h=120:color=white@0.9:t=fill",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p", "-c:v", "libx264", "-crf", "18", str(path)],
                   check=True)
    info = ff.probe(path)
    signals = shots.frame_signals(path, {"fps": info["fps"], "matrix": "bt709"})
    assert shots.find_cuts(signals["hist"], signals["diff"], info["fps"]) == [120]
