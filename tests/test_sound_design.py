"""Voice treatment, the speech-band carve, echo throws, and what the checker says about voice level."""
import numpy as np
import pytest
from scipy.signal import butter, sosfilt

from workprint import check, cli, ff, manifest, mix, vox
from tests.test_voice import SCRIPT, make_speech, no_tools, three_slot_cut  # noqa: F401

SR = 48000


def power(x, lo, hi):
    y = sosfilt(butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), x, axis=0)
    return 10 * np.log10(np.mean(y ** 2) + 1e-15)


def burst(rng, seconds=2.0):
    t = np.arange(int(seconds * SR)) / SR
    return rng.normal(0, 0.1, len(t)) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))


def test_treatments_do_what_they_say():
    x = burst(np.random.default_rng(1))
    clear = vox.treat(x, SR, vox.settings("clear"))
    lift = (power(clear[:, 0], 2500, 4500) - power(clear[:, 0], 150, 250)) - (power(x, 2500, 4500) - power(x, 150, 250))
    assert clear.shape[1] == 2 and lift > 2.0  # consonants up relative to the low mids
    assert power(clear[:, 0], 20, 60) < power(x, 20, 60) - 6  # rumble gone
    hall = vox.treat(x, SR, vox.settings("hall"))
    tail = hall[len(x) + SR // 10:]
    assert len(hall) > len(x) + 2 * SR and np.abs(tail[:SR // 2]).max() > 1e-3  # the room rings on after the voice stops
    assert np.abs(tail[-SR // 4:]).max() < 0.15 * np.abs(tail[:SR // 4]).max()  # and dies away
    radio = vox.treat(x, SR, vox.settings("radio"))
    assert power(radio[:, 0], 6000, 12000) < power(x, 6000, 12000) - 15
    assert vox.settings("none") is None and vox.settings({"preset": "hall", "reverb": 0.4})["reverb"] == 0.4
    with pytest.raises(ValueError):
        vox.settings("cathedral")


def test_the_carve_takes_only_the_speech_band_and_only_under_speech():
    rng = np.random.default_rng(2)
    music = rng.normal(0, 0.1, (4 * SR, 2))
    active = np.r_[np.zeros(2 * SR), np.ones(2 * SR)]
    out = vox.carve(music, active, SR, -9.0)
    quiet, loud = slice(SR // 2, 3 * SR // 2), slice(5 * SR // 2, 7 * SR // 2)
    assert np.allclose(out[quiet], music[quiet], atol=1e-9)
    assert -9.5 < power(out[loud], 800, 2500) - power(music[loud], 800, 2500) < -6.5
    assert abs(power(out[loud], 30, 100) - power(music[loud], 30, 100)) < 0.6  # the low end stays
    assert abs(power(out[loud], 9000, 15000) - power(music[loud], 9000, 15000)) < 0.6  # so does the air
    assert vox.carve(music, active, SR, 0.0) is music


def test_a_throw_repeats_the_word_in_time_and_fades():
    bus = np.zeros((4 * SR, 2))
    bus[SR:SR + SR // 5] = np.random.default_rng(3).normal(0, 0.2, (SR // 5, 2))
    echo = vox.throw(bus, SR, 1.0, 0.2, 0.5, repeats=3, feedback=0.5)
    level = [np.sqrt(np.mean(echo[int((1.0 + 0.5 * k) * SR):int((1.2 + 0.5 * k) * SR)] ** 2)) for k in range(5)]
    assert level[0] == 0 and level[4] == 0 and level[1] > level[2] > level[3] > 0
    assert 0.3 < level[2] / level[1] < 0.6


def test_voice_level_is_measured_and_improved_by_the_carve(project, tmp_path, no_tools):
    root = str(project.root)
    cut = three_slot_cut(project)
    cut["music"] = {"in": 12.5, "gain_db": 0}
    project.save_cut(cut, "with music")
    assert cli.main(["-p", root, "voice", "add", str(make_speech(tmp_path / "v.wav")), "--script", SCRIPT]) == 0
    assert cli.main(["-p", root, "voice", "place", "V01", "--at", "0.75", "--gain", "-14"]) == 0
    project = type(project)(project.root)
    plain = mix.build(project, project.cut())
    assert cli.main(["-p", root, "set", "audio", "carve_db=-10"]) == 0
    carved = mix.build(project, project.cut())
    assert carved["voice_over_music_db"] > plain["voice_over_music_db"] + 2.5
    assert cli.main(["-p", root, "set", "v001", "treat=hall"]) == 0
    assert cli.main(["-p", root, "voice", "throw", "v001", "--word", "will"]) == 0
    cut = project.cut()
    assert cut["voice"][0]["throws"][0]["word"] == "will." and cut["voice"][0]["throws"][0]["delay"] > 0
    carved = mix.build(project, cut)
    assert carved["true_peak"] <= -0.5 and np.isfinite(ff.read_audio(carved["path"], SR, 2)).all()
    errors, _ = manifest.validate({**cut, "voice": [{**cut["voice"][0], "treat": "cathedral"}]}, project)
    assert any("cathedral" in e for e in errors)
    quiet = {**cut, "audio": {"target_lufs": -16.0}, "voice": [{**cut["voice"][0], "gain_db": -30, "treat": "none", "throws": []}]}
    from workprint.render import render
    out = project.root / "q.mp4"
    render(project, quiet, out, 0.5, 30, "ultrafast", progress=lambda *_: None)
    report = check.check(project, quiet, out, write_review=False)
    assert report["speech"]["voice_over_music_db"] < 6 and any("hard to follow" in f["text"] for f in report["findings"])


def drum_track(path, bpm=120.0, bars=8):
    rng = np.random.default_rng(5)
    beat = 60.0 / bpm
    total = bars * 4 * beat + 1.0
    t = np.arange(int(total * SR)) / SR
    x = 0.05 * np.sin(2 * np.pi * 220 * t) + 0.04 * np.sin(2 * np.pi * 660 * t)  # a held chord that must not count
    truth = {"kick": [], "snare": [], "hat": []}

    def add(at, sound):
        i = int(at * SR)
        x[i:i + len(sound)] += sound[:len(x) - i]

    for k in range(bars * 8):
        at = 0.5 + k * beat / 2
        n = int(0.03 * SR)
        add(at, sosfilt(butter(4, 7500, "highpass", fs=SR, output="sos"), rng.normal(0, 0.25, n)) * np.exp(-np.arange(n) / (0.006 * SR)))
        truth["hat"].append(at)
        if k % 4 == 0:
            n = int(0.18 * SR)
            tt = np.arange(n) / SR
            add(at, 0.8 * np.sin(2 * np.pi * (45 * tt + 60 * 0.05 * (1 - np.exp(-tt / 0.05)))) * np.exp(-tt / 0.06))
            truth["kick"].append(at)
        if k % 4 == 2:
            n = int(0.14 * SR)
            add(at, sosfilt(butter(2, [200, 9000], "bandpass", fs=SR, output="sos"), rng.normal(0, 0.5, n)) * np.exp(-np.arange(n) / (0.03 * SR)))
            truth["snare"].append(at)
    ff.write_wav(path, x[:, None], SR)
    return truth


def test_drum_hits_are_found_by_kind(tmp_path):
    from workprint import music
    truth = drum_track(tmp_path / "d.wav")
    found = music.analyze(tmp_path / "d.wav")["drums"]
    for kind, need in (("kick", 0.9), ("snare", 0.9), ("hat", 0.75)):
        hits = np.array(found[kind])
        want = np.array(truth[kind]) if kind != "hat" else np.array([t for t in truth["hat"] if t not in truth["snare"]])
        recall = np.mean([np.abs(hits - t).min() < 0.03 for t in want]) if len(hits) else 0.0
        precision = np.mean([np.abs(np.array(truth[kind]) - h).min() < 0.03 for h in hits]) if len(hits) else 0.0
        assert recall >= need and precision >= need, f"{kind}: recall {recall:.2f}, precision {precision:.2f}, {len(hits)} found"
    log = {"drums": found}
    assert abs(music.nearest_hit(log, "snare", truth["snare"][2] + 0.04) - truth["snare"][2]) < 0.03
    assert music.nearest_hit(log, "snare", 1.23, within=0.01) == 1.23


def test_cuts_can_land_on_the_kick(project):
    from workprint import planner, revise
    log = project.music()
    kicks = np.array(log["drums"]["kick"])
    assert len(kicks) > 8
    start = float(kicks[4]) - 0.01
    structure = {"duration": 6.0, "music_in": start, "sections": [{"name": "drums", "from": 0, "to": 6.0, "energy": 0.8, "every": 2, "on": "kick"}]}
    cut = planner.draft(project, structure)
    for entry in cut["cuts"][1:]:
        assert np.abs(kicks - (entry["at"] + start)).min() <= 0.5 / 24 + 0.012, f"{entry['id']} at {entry['at']} is not on a kick"
    target = cut["cuts"][2]
    wanted = float(kicks[np.argmin(np.abs(kicks - (target["at"] + start + 0.2)))]) - start
    revise.roll(cut, target["id"], to=target["at"] + 0.2, analysis=log, on="kick")
    assert abs(target["at"] - wanted) < 1e-3


def test_noise_reduction_lowers_the_floor_and_keeps_the_voice():
    rng = np.random.default_rng(8)
    t = np.arange(6 * SR) / SR
    voice_part = np.zeros_like(t)
    for a, b in ((0.8, 2.0), (3.0, 4.4)):
        m = (t >= a) & (t < b)
        voice_part[m] = 0.2 * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t[m])) * sum(np.sin(2 * np.pi * f * t[m]) / k for k, f in enumerate((150, 450, 900, 1800, 2700), 1))
    noisy = voice_part + rng.normal(0, 0.01, len(t)) + 0.02 * np.sin(2 * np.pi * 60 * t)
    clean = vox.denoise(noisy, SR, 0.8)
    rms = lambda x, a, b: 20 * np.log10(np.sqrt(np.mean(x[int(a * SR):int(b * SR)] ** 2)) + 1e-12)
    assert rms(clean, 4.8, 5.8) < rms(noisy, 4.8, 5.8) - 12  # the pause is much quieter
    assert abs(rms(clean, 1.0, 1.9) - rms(noisy, 1.0, 1.9)) < 1.5  # the voice keeps its level
    assert len(clean) == len(noisy) and vox.denoise(noisy, SR, 0.0) is noisy
    restored = vox.treat(noisy, SR, vox.settings("restore"))
    assert restored.shape == (len(noisy), 2) and rms(restored[:, 0], 4.8, 5.8) < rms(noisy, 4.8, 5.8) - 12


# ---- the wider effects kit (0.6) ------------------------------------------------------------------
def test_every_sound_in_the_kit_builds_and_is_the_same_each_time():
    from workprint import manifest, sound
    assert set(sound.KIT) == set(manifest.SOUND_KINDS) == set(sound.TRIM)
    for kind in sound.KIT:
        spec = {"id": "s001", "kind": kind, "db": -10}
        audio, lead = sound.make(spec)
        again, _ = sound.make(spec)
        assert audio.ndim == 2 and audio.shape[1] == 2 and len(audio) > 0.04 * sound.SR, kind
        assert np.isfinite(audio).all() and np.array_equal(audio, again), kind
        assert 0.0 <= lead <= len(audio) / sound.SR + 1e-6, kind
        assert abs(np.abs(audio).max() - sound.db(-10 + sound.TRIM[kind])) < 1e-6, kind


def test_long_sounds_take_a_length_and_a_reverse_ends_on_its_hit():
    from workprint import sound
    for kind in ("rocket", "hum", "reverse"):
        audio, lead = sound.make({"id": "s001", "kind": kind, "db": -12, "dur": 2.0})
        assert abs(len(audio) / sound.SR - 2.0) < 0.01, kind
    assert sound.make({"id": "s001", "kind": "reverse", "dur": 2.0})[1] == 2.0   # all of it comes before the cut
    rocket, _ = sound.make({"id": "s001", "kind": "rocket", "dur": 4.0})
    quarter = len(rocket) // 4
    assert np.abs(rocket[:quarter]).mean() > 3 * np.abs(rocket[-quarter:]).mean()   # starts hard, dies away

