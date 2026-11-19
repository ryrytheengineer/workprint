"""Voice, captions, voice-led cutting and aspect versions.

The speech here is synthetic (harmonic bursts with pauses), so these tests cover the
measurement, timing, drawing and caching logic. Transcription by the optional speech
model is exercised only where that model is installed.
"""
import json

import numpy as np
import pytest

from workprint import captions, check, cli, ff, manifest, planner, versions, voice
from workprint.render import plan, render

SPANS = [(0.5, 1.4), (2.0, 3.1), (3.9, 4.8)]
SCRIPT = "We have the men, the skill, the wealth, and above all, the will."


def make_speech(path, spans=SPANS, total=6.0, sr=48000):
    t = np.arange(int(total * sr)) / sr
    x = np.random.default_rng(3).normal(0, 0.001, len(t))
    for a, b in spans:
        m = (t >= a) & (t < b)
        syllable = 0.6 + 0.4 * np.sin(2 * np.pi * 4.5 * (t[m] - a) - np.pi / 2)
        x[m] += 0.2 * syllable * sum(np.sin(2 * np.pi * f * t[m]) / k for k, f in enumerate((140, 420, 700, 1120, 1680), 1))
    ff.write_wav(path, x[:, None], sr)
    return path


@pytest.fixture()
def no_tools(monkeypatch):
    monkeypatch.setattr(voice, "tools", lambda: {"aligner": False, "recognizer": False, "model": False})


def three_slot_cut(project) -> dict:
    cut = manifest.new_cut(project.format, 6.0, "voice test")
    cut["audio"] = {"target_lufs": -16.0}
    cut["cuts"] = [{"at": 0.0, "src": "A003", "in": 0.5}, {"at": 2.0, "src": "A001", "in": 0.2}, {"at": 4.0, "src": "A004", "in": 0.0}]
    return manifest.normalize(cut)


def test_phrases_are_found_between_pauses(tmp_path):
    found = voice.find_phrases(voice.envelope(voice.load(make_speech(tmp_path / "v.wav"))))
    assert len(found) == len(SPANS)
    for (a, b), (fa, fb) in zip(SPANS, found):
        assert abs(a - fa) < 0.06 and abs(b - fb) < 0.08


def test_a_script_without_tools_is_spread_and_says_so(tmp_path, no_tools):
    result = voice.analyze(make_speech(tmp_path / "v.wav"), script=SCRIPT)
    assert result["method"] == "spread" and result["approximate"] and result["notes"]
    assert [w["w"] for w in result["words"]] == SCRIPT.split()
    starts = [w["s"] for w in result["words"]]
    assert starts == sorted(starts)
    for a, _ in result["phrases"]:  # every phrase opens exactly on a word
        assert min(abs(s - a) for s in starts) < 1e-6
    assert all(0.0 <= w["stress"] <= 1.0 for w in result["words"])


def test_without_words_only_phrases_are_reported(tmp_path, no_tools):
    result = voice.analyze(make_speech(tmp_path / "v.wav"))
    assert result["method"] == "phrases-only" and not result["words"] and len(result["phrases"]) == 3


def test_word_files_are_read(tmp_path):
    whisper = {"segments": [{"words": [{"word": " Hello", "start": 0.5, "end": 0.8}, {"word": " world.", "start": 0.9, "end": 1.3}]}]}
    (tmp_path / "w.json").write_text(json.dumps(whisper))
    assert voice.read_words(tmp_path / "w.json") == [{"w": "Hello", "s": 0.5, "e": 0.8}, {"w": "world.", "s": 0.9, "e": 1.3}]
    (tmp_path / "w.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nOne two three\n\n2\n00:00:04,000 --> 00:00:05,000\nfour\n")
    words = voice.read_words(tmp_path / "w.srt")
    assert [w["w"] for w in words] == ["One", "two", "three", "four"] and words[0]["s"] == 1.0 and words[3]["s"] == 4.0


def test_retext_keeps_the_times_and_takes_the_spelling():
    heard = [{"w": "we", "s": 0.1, "e": 0.3}, {"w": "have", "s": 0.3, "e": 0.6}, {"w": "the", "s": 0.6, "e": 0.7}, {"w": "man", "s": 0.7, "e": 1.2}]
    fixed = voice.retext(heard, "We have the MEN,")
    assert [w["w"] for w in fixed] == ["We", "have", "the", "MEN,"]
    assert [w["s"] for w in fixed] == [0.1, 0.3, 0.6, 0.7]


def timed(text, start=1.0, step=0.4, gaps=()):
    out, t = [], start
    for n, word in enumerate(text.split()):
        t += 0.6 if n in gaps else 0.0
        out.append({"w": word, "s": round(t, 3), "e": round(t + step * 0.8, 3)})
        t += step
    return out


def test_cues_follow_phrasing_and_punch_words_stand_alone():
    words = timed("We have the men, the skill, the wealth, and above all, the will.", gaps=(4, 8))
    cues = captions.from_words(words, "split", punch=["will"], voice="v001")
    assert [c["style"] for c in cues][-1] == "punch" and cues[-1]["text"] == "will"
    assert all(c["voice"] == "v001" for c in cues)
    assert " ".join(c["text"] for c in cues[:-1]).split() == "We have the men, the skill, the wealth, and above all, the".split()
    for a, b in zip(cues, cues[1:]):
        assert a["at"] + a["dur"] <= b["at"]
    second = captions.from_words(timed("more ships more guns more planes"), "line", punch=["more:2"])
    assert [c["text"] for c in second] == ["more ships", "more", "guns more planes"]


def test_a_line_builds_word_by_word_without_moving():
    cue = {"at": 1.0, "dur": 2.0, "text": "tomorrow will be later", "style": "line",
           "words": [[0.0, "tomorrow"], [0.5, "will"], [0.9, "be"], [1.2, "later"]]}
    pieces = captions.compile_cue(cue, 24.0, 960, 540)
    assert [p["hi"] for p in pieces] == [1, 2, 3, 4] and len({id(p["block"]) for p in pieces}) == 1
    assert [p["f0"] for p in pieces] == [24, 36, 46, 53] and pieces[-1]["f1"] == 72
    early, late = np.zeros((540, 960, 3), np.uint8), np.zeros((540, 960, 3), np.uint8)
    captions.draw(pieces, early, 30)
    captions.draw(pieces, late, 60)
    x0, y0, x1, y1 = pieces[0]["block"].box(0, 1)
    assert early[y0:y1, x0:x1].max() > 200
    assert np.array_equal(early[y0:y1, x0:x1 - 2], late[y0:y1, x0:x1 - 2])  # the first word has not shifted
    assert late[:, x1 + 4:].max() > 200 and early[:, x1 + 4:].max() == 0  # later words arrive later


def test_split_and_punch_layouts():
    wide = captions.compile_cue({"at": 0, "dur": 2, "text": "in this day of electricity", "style": "split",
                                 "words": [[0, "in"], [0.2, "this"], [0.4, "day"], [1.0, "of"], [1.2, "electricity"]]}, 24.0, 1920, 1080)
    right, left = wide
    assert left["block"].box()[2] < 960 < right["block"].box()[0] and right["f0"] == 24  # middle left clear; second half on its word
    tall = captions.compile_cue({"at": 0, "dur": 2, "text": "in this day of electricity", "style": "split"}, 24.0, 1080, 1920)
    assert tall[1]["block"].box()[3] <= tall[0]["block"].box()[1] + 4  # stacked on a tall frame
    punch = captions.compile_cue({"at": 0, "dur": 1, "text": "genius.", "style": "punch"}, 24.0, 1920, 1080)[0]
    x0, y0, x1, y1 = punch["block"].box()
    assert punch["dim"] == 0.5 and 0.7 * 1920 < x1 - x0 <= 0.81 * 1920 and abs((y0 + y1) / 2 - 540) < 6
    errors, warnings = captions.problems({"format": {"fps": 24}, "duration": 5, "captions": [
        {"id": "k1", "at": 0, "dur": 0.1, "text": "hi", "style": "line"}, {"id": "k2", "at": 1, "dur": 1, "text": "x", "style": "nope"}]})
    assert any("nope" in e for e in errors) and any("too short" in w for w in warnings)


def test_captions_only_re_render_the_chunks_they_sit_on(project):
    cut = three_slot_cut(project)
    before = plan(project, cut, 0.5, 30, "ultrafast")
    render(project, cut, project.root / "a.mp4", 0.5, 30, "ultrafast", progress=lambda *_: None)
    cut["captions"] = [{"id": "k001", "at": 2.4, "dur": 1.2, "text": "above all", "style": "word"}]
    after = plan(project, cut, 0.5, 30, "ultrafast")
    assert [p == q for p, q in zip(before["paths"], after["paths"])] == [True, False, True] and after["todo"] == [1]
    render(project, cut, project.root / "b.mp4", 0.5, 30, "ultrafast", progress=lambda *_: None)
    a, b = ff.grab_frame(project.root / "a.mp4", 3.0), ff.grab_frame(project.root / "b.mp4", 3.0)
    assert np.abs(a.astype(int) - b.astype(int)).max() > 80  # the words are in the picture
    a, b = ff.grab_frame(project.root / "a.mp4", 1.0), ff.grab_frame(project.root / "b.mp4", 1.0)
    assert np.array_equal(a, b)


def test_voice_to_captions_from_the_command_line(project, tmp_path, no_tools, capsys):
    root = str(project.root)
    project.save_cut(three_slot_cut(project), "three slots")
    assert cli.main(["-p", root, "voice", "add", str(make_speech(tmp_path / "v.wav")), "--script", SCRIPT]) == 0
    assert "13 words in 3 phrases (spread, approximate)" in capsys.readouterr().out
    assert cli.main(["-p", root, "voice", "place", "V01", "--at", "0.75"]) == 0
    assert cli.main(["-p", root, "captions", "--style", "line", "--punch", "will", "--accent"]) == 0
    assert cli.main(["-p", root, "new", "caption", "at=0.1", "text=A note", "style=line"]) == 0
    project = type(project)(project.root)  # the commands above changed the project on disk
    cut = project.cut()
    item = cut["voice"][0]
    assert item["src"] == "V01" and abs(item["at"] + (0.5 - item["in"]) - 0.75) < 0.03  # first word lands where asked
    made = [c for c in cut["captions"] if c.get("voice")]
    assert made[-1]["style"] == "punch" and [s["note"] for s in cut["sounds"]] == ["accent: will"]
    assert cli.main(["-p", root, "captions", "--style", "word"]) == 0  # a second run replaces the first, keeps hand-made cues
    cut = project.cut()
    assert {c["style"] for c in cut["captions"] if c.get("voice")} == {"word"} and not cut["sounds"]
    assert [c["text"] for c in cut["captions"] if not c.get("voice")] == ["A note"]
    out = project.root / "v.mp4"
    stats = render(project, cut, out, 0.5, 30, "ultrafast", progress=lambda *_: None)
    assert stats["audio"]["true_peak"] is not None and stats["audio"]["true_peak"] <= -0.5
    report = check.check(project, cut, out, write_review=False)
    assert report["verdict"] != "FAIL" and report["speech"]["words"] == 13 and report["speech"]["phrases"] == 3
    cut["voice"][0]["at"] += 0.5  # move the voice without its captions: the check notices
    report = check.check(project, cut, out, write_review=False)
    assert any("off the voice" in f["text"] for f in report["findings"])


def test_the_planner_cuts_on_the_breath(project, tmp_path, no_tools):
    entry = project.add_voice(make_speech(tmp_path / "v.wav", total=8.0, spans=[(1.1, 2.6), (3.7, 5.2), (6.3, 7.4)]))
    project.save()
    log = voice.analyze(project.path_of(entry), script="one two three four five six")
    (project.log_dir / f"voice-{entry['id']}.json").write_text(json.dumps(log))
    structure = {"duration": 8.0, "music_in": 12.5, "voice": [{"src": entry["id"], "at": 0.0}],
                 "sections": [{"name": "spoken", "from": 0.0, "to": 8.0, "energy": 0.5, "every": 2, "follow": "voice"}]}
    cut = planner.draft(project, structure)
    times = [c["at"] for c in cut["cuts"]]
    for a, b in log["phrases"]:
        assert any(-1 / 24 <= a - t <= 0.2 for t in times), f"no cut just ahead of the phrase at {a}"
        assert not any(a + 1 / 24 < t < b for t in times), "a cut landed while the voice was speaking"
    plain = planner.draft(project, {**structure, "sections": [{**structure["sections"][0], "follow": None}]})
    assert len(plain["cuts"]) > len(cut["cuts"])


def test_versions_reframe_and_render(project):
    assert versions.parse("9:16") == ("9x16", 0.5625) and versions.size_for({"width": 1920, "height": 1080}, 0.5625) == (1080, 1920)
    assert versions.size_for({"width": 1920, "height": 1080}, 1.0) == (1080, 1080)
    assert versions._window(np.r_[np.zeros(80), np.ones(20)], 0.2) == 1.0 and versions._window(np.ones(100), 0.3) == 0.5
    cut = three_slot_cut(project)
    done = versions.propose(project, cut, "9x16", 0.5625)
    assert len(done) == 3 and all("focus_9x16" in c for c in cut["cuts"])
    main = plan(project, cut, 0.5, 30, "ultrafast")
    cut["cuts"][0]["focus_9x16"] = [0.0, 0.5]
    assert plan(project, cut, 0.5, 30, "ultrafast")["paths"] == main["paths"]  # the 16:9 film does not care
    out = project.root / "tall.mp4"
    render(project, cut, out, 0.5, 30, "ultrafast", progress=lambda *_: None, aspect="9:16")
    info = ff.probe(out)
    assert abs(info["width"] / info["height"] - 0.5625) < 0.01
    left = ff.grab_frame(out, 1.0)
    cut["cuts"][0]["focus_9x16"] = [1.0, 0.5]
    job = plan(project, cut, 0.5, 30, "ultrafast", "9:16")
    assert job["todo"] == [0]  # moving one shot's frame redoes one chunk of the version
    render(project, cut, out, 0.5, 30, "ultrafast", progress=lambda *_: None, aspect="9:16")
    assert np.abs(left.astype(int) - ff.grab_frame(out, 1.0).astype(int)).mean() > 2
    report = check.check(project, cut, out, write_review=False)
    assert report["verdict"] != "FAIL" and any("version of the cut" in f["text"] for f in report["findings"])
    assert versions.sheet(project, cut, "9x16", 0.5625, project.root / "review" / "reframe.jpg").exists()


@pytest.mark.skipif(not all(voice.tools().values()), reason="the optional speech model is not installed")
def test_the_speech_model_loads():
    silence = np.zeros(voice.SR * 2)
    assert voice.transcribe(silence, []) == []



# ---- checking excerpts as cut (0.6) -------------------------------------------------------------
def placed_excerpts(project, tmp_path, excerpts, captions_for=None):
    """A cut with the synthetic speech placed as the given (in, dur) excerpts."""
    entry = project.add_voice(make_speech(tmp_path / "v.wav"))
    project.save()
    (project.log_dir / f"voice-{entry['id']}.json").write_text(json.dumps(
        {"duration": 6.0, "phrases": [list(s) for s in SPANS], "method": "imported", "approximate": False,
         "words": [{"w": w, "s": a, "e": b, "stress": 0.5} for w, (a, b) in zip(("one", "two", "three"), SPANS)]}))
    cut = three_slot_cut(project)
    cut["voice"] = [{"id": f"v{i + 1:03d}", "src": entry["id"], "at": 0.5 * i, "in": a, "dur": d} for i, (a, d) in enumerate(excerpts)]
    if captions_for:
        cut["captions"] = [{"id": "k001", "at": 0.0, "dur": 1.0, "text": captions_for, "style": "line", "voice": "v001"}]
    return cut


def test_an_excerpt_cut_in_the_pauses_passes(project, tmp_path, no_tools):
    report = voice.check_placed(project, placed_excerpts(project, tmp_path, [(0.3, 1.4), (1.8, 1.6)]))
    assert [r["problems"] for r in report] == [[], []]
    assert abs(report[0]["lead"] - 0.2) < 0.05 and abs(report[0]["tail"] - 0.3) < 0.05
    assert report[0]["heard"] is None  # no speech model here: only the edges were looked at


def test_an_excerpt_that_starts_or_stops_inside_a_word_is_flagged(project, tmp_path, no_tools):
    inside_start, inside_end, tight_end = voice.check_placed(project, placed_excerpts(project, tmp_path, [(0.9, 0.8), (1.8, 0.9), (1.8, 1.33)]))
    assert inside_start["starts_inside"] and any("starts inside" in p for p in inside_start["problems"])
    assert inside_end["ends_inside"] and any("ends inside" in p for p in inside_end["problems"])
    assert not tight_end["ends_inside"] and tight_end["tail"] < 0.08 and any("may be cut" in p for p in tight_end["problems"])


def test_words_that_are_not_in_the_excerpt_are_reported(project, tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "tools", lambda: {"aligner": False, "recognizer": True, "model": True})
    monkeypatch.setattr(voice, "_recognize", lambda x: [{"w": "And", "s": 0.1}, {"w": "um", "s": 0.4}])
    cut = placed_excerpts(project, tmp_path, [(0.3, 1.4)], captions_for="And that's the sales pitch.")
    row = voice.check_placed(project, cut)[0]
    assert row["heard"] == "And um" and row["expected_from"] == "captions"
    assert row["missing"] == ["that's", "the", "sales", "pitch."] and row["extra"] == ["um"]
    assert any("differ" in p for p in row["problems"])


def test_voice_check_command_fails_when_an_excerpt_is_clipped(project, tmp_path, no_tools, capsys):
    project.save_cut(manifest.normalize(placed_excerpts(project, tmp_path, [(0.9, 0.8)])), "clipped")
    assert cli.main(["-p", str(project.root), "voice", "check"]) == 1
    out = capsys.readouterr().out
    assert "WARN v001" in out and "starts inside" in out and "only the edges were checked" in out
    project.save_cut(manifest.normalize(placed_excerpts(project, tmp_path, [(0.3, 1.4)])), "clean")
    assert cli.main(["-p", str(project.root), "voice", "check"]) == 0
