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
