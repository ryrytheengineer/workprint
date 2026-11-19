"""Voice: where the words are.

A picture editor cutting to a voice needs three things from the recording: where the
speaker starts and stops (phrases and pauses), when each word lands, and which words
are leaned on. This module measures all three and writes them to the project log.

Phrases come from Workprint's own analysis and need nothing extra. Word times come
from the best source available, in this order:

1. a word file you already have (Whisper-style JSON, SRT or VTT);
2. transcription by a local speech model, with every word then re-timed against the
   audio by a forced aligner (the optional ``voice`` tools: ``workprint voice setup``);
3. a script you supply, aligned to the audio (needs only the aligner);
4. a script spread across the phrases by syllable count: approximate, and marked so.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d, median_filter, uniform_filter1d
from scipy.signal import butter, sosfiltfilt

from . import ff

VOICE_REV = 1
SR = 16000
HOP = 0.01  # seconds per envelope frame
WINDOW = 24.0  # longest stretch handed to the speech model at once

# The speech model is fetched only by `workprint voice setup --yes`, from this address,
# and is used only if its checksum matches.
MODEL = {
    "name": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
    "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
    "sha256": "6fc4426b54aa549a0019b8a75b8dea59164e71790a37ac56a045ad57f915f714",
    "bytes": 482440461,
    "license": "CC BY 4.0 (weights by NVIDIA; ONNX export by the sherpa-onnx project)",
    "files": ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"),
}
PACKAGES = ("pocketsphinx>=5.0", "sherpa-onnx>=1.10")


class VoiceError(RuntimeError):
    pass


# ---- optional tools ------------------------------------------------------------------------
def home() -> Path:
    return Path(os.environ.get("WORKPRINT_HOME") or Path.home() / ".workprint")


def model_dir() -> Path:
    return home() / "models" / MODEL["name"]


def _importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def tools() -> dict:
    """Which optional voice tools are present."""
    folder = model_dir()
    return {"aligner": _importable("pocketsphinx"), "recognizer": _importable("sherpa_onnx"),
            "model": all((folder / name).exists() for name in MODEL["files"])}


def setup(progress=print) -> dict:
    """Install the aligner and recognizer packages and fetch the speech model. Explicit and checksum-verified."""
    missing = [p for p, name in zip(PACKAGES, ("pocketsphinx", "sherpa_onnx")) if not _importable(name)]
    if missing:
        progress(f"installing {', '.join(missing)}")
        uv = shutil.which("uv")  # an environment made by uv has no pip of its own
        command = ([uv, "pip", "install", "--quiet", "--python", sys.executable] if uv else
                   [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"])
        done = subprocess.run([*command, *missing], capture_output=True, text=True)
        if done.returncode:
            raise VoiceError("pip could not install the voice tools:\n" + done.stderr.strip()[-600:])
    if not tools()["model"]:
        folder = model_dir()
        folder.parent.mkdir(parents=True, exist_ok=True)
        archive = folder.parent / (MODEL["name"] + ".tar.bz2")
        progress(f"downloading the speech model ({MODEL['bytes'] / 1e6:.0f} MB) from {MODEL['url']}")
        digest = hashlib.sha256()
        with urllib.request.urlopen(MODEL["url"], timeout=60) as response, open(archive, "wb") as out:
            while block := response.read(1 << 20):
                digest.update(block)
                out.write(block)
        if digest.hexdigest() != MODEL["sha256"]:
            archive.unlink(missing_ok=True)
            raise VoiceError("the downloaded model does not match its expected checksum; nothing was installed")
        with tarfile.open(archive, "r:bz2") as tar:  # extract only the plain files we name
            for member in tar.getmembers():
                name = Path(member.name).name
                if member.isfile() and name in MODEL["files"] and Path(member.name).parent.name == MODEL["name"]:
                    folder.mkdir(exist_ok=True)
                    with tar.extractfile(member) as src, open(folder / name, "wb") as out:
                        while block := src.read(1 << 20):
                            out.write(block)
        archive.unlink(missing_ok=True)
    return tools()


# ---- phrases ---------------------------------------------------------------------------------
def load(path) -> np.ndarray:
    return ff.read_audio(path, SR, 1)[:, 0].astype(np.float64)


def envelope(x: np.ndarray) -> np.ndarray:
    """Speech-band level in dB, one value per 10 ms."""
    if len(x) < SR // 10:
        return np.full(max(1, int(len(x) / (SR * HOP))), -90.0)
    band = sosfiltfilt(butter(4, [250, 3800], "bandpass", fs=SR, output="sos"), x)
    step = int(SR * HOP)
    power = uniform_filter1d(band ** 2, size=int(SR * 0.025))[step // 2::step]
    return 10.0 * np.log10(power + 1e-12)


def _runs(mask: np.ndarray) -> list[list[int]]:
    edges = np.flatnonzero(np.diff(np.r_[0, mask.astype(np.int8), 0]))
    return [[int(a), int(b)] for a, b in zip(edges[::2], edges[1::2])]


def find_phrases(db: np.ndarray, pause: float = 0.35) -> list[list[float]]:
    """Stretches of continuous speech, split wherever the speaker stops for ``pause`` seconds or more."""
    floor, top = np.percentile(db, 10), np.percentile(db, 95)
    if top - floor < 6.0:  # no contrast between speech and pause: one phrase, or silence
        return [[0.0, round(len(db) * HOP, 3)]] if top > -60 else []
    threshold = floor + max(6.0, 0.3 * (top - floor))
    active = median_filter((db > threshold).astype(np.uint8), size=5).astype(bool)
    merged: list[list[int]] = []
    for a, b in _runs(active):
        if merged and a - merged[-1][1] < 0.15 / HOP:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    merged = [r for r in merged if r[1] - r[0] >= 0.08 / HOP]
    phrases: list[list[int]] = []
    for a, b in merged:
        if phrases and a - phrases[-1][1] < pause / HOP:
            phrases[-1][1] = b
        else:
            phrases.append([a, b])
    return [[round(a * HOP, 3), round(b * HOP, 3)] for a, b in phrases]


# ---- text helpers ------------------------------------------------------------------------------
def tokens_of(text: str) -> list[str]:
    """Words as they should be shown, punctuation attached."""
    return [t for t in re.split(r"\s+", text.replace("—", " — ").strip()) if re.search(r"\w", t)]


def plain(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower().replace("’", "'")).strip("'")


def syllables(word: str) -> int:
    w = plain(word)
    if w.isdigit():
        return max(1, 2 * len(w))
    groups = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and groups > 1:
        groups -= 1
    return max(1, groups)


# ---- word times ----------------------------------------------------------------------------------
def _windows(phrases: list[list[float]], total: float) -> list[tuple[float, float]]:
    """Cover the recording with stretches of at most WINDOW seconds, breaking only in pauses."""
    if not phrases:
        return [(0.0, total)] if total <= WINDOW else [(t, min(total, t + WINDOW)) for t in np.arange(0.0, total, WINDOW)]
    marks = [0.0] + [(a[1] + b[0]) / 2 for a, b in zip(phrases, phrases[1:])] + [total]
    out, start = [], 0.0
    for prev, mark in zip(marks, marks[1:]):
        if mark - start > WINDOW and prev > start:
            out.append((start, prev))
            start = prev
    out.append((start, total))
    return [w for a, b in out for w in ([(a, b)] if b - a <= 2 * WINDOW else
                                      [(t, min(b, t + WINDOW)) for t in np.arange(a, b, WINDOW)])]


_recognizer = None


def _recognize(x: np.ndarray) -> list[dict]:
    global _recognizer
    import sherpa_onnx
    if _recognizer is None:
        d = model_dir()
        _recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"), joiner=str(d / "joiner.int8.onnx"),
            tokens=str(d / "tokens.txt"), model_type="nemo_transducer", num_threads=max(1, min(4, os.cpu_count() or 1)))
    stream = _recognizer.create_stream()
    stream.accept_waveform(SR, x.astype(np.float32))
    _recognizer.decode_stream(stream)
    words: list[dict] = []
    for token, t in zip(stream.result.tokens, stream.result.timestamps):
        if token[:1] in (" ", "▁") or not words:
            words.append({"w": token.strip(" ▁"), "s": float(t)})
        else:
            words[-1]["w"] += token
    return [w for w in words if re.search(r"\w", w["w"])]


def _align(x: np.ndarray, words: list[str]) -> list[tuple[float, float] | None]:
    """Forced alignment of known words to audio. None for a word the aligner could not place."""
    from pocketsphinx import Decoder
    decoder = Decoder(samprate=SR, loglevel="FATAL")
    keys = [plain(w) for w in words]
    known = [i for i, k in enumerate(keys) if k and decoder.lookup_word(k) is not None]
    result: list[tuple[float, float] | None] = [None] * len(words)
    if not known:
        return result
    try:
        decoder.set_align_text(" ".join(keys[i] for i in known))
        decoder.start_utt()
        decoder.process_raw((np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes(), full_utt=True)
        decoder.end_utt()
        segments = [(s.word.split("(")[0], s.start_frame / 100.0, (s.end_frame + 1) / 100.0) for s in decoder.seg()
                    if not s.word.startswith("<") and s.word != "(NULL)"]
    except Exception:
        return result
    if [s[0] for s in segments] == [keys[i] for i in known]:
        for i, (_, a, b) in zip(known, segments):
            result[i] = (a, b)
    return result


def transcribe(x: np.ndarray, phrases: list[list[float]]) -> list[dict]:
    """Words and their times from the local speech model, each re-timed by the aligner where it agrees."""
    have = tools()
    if not (have["recognizer"] and have["model"]):
        raise VoiceError("transcription needs the voice tools: run `workprint voice setup`")
    words: list[dict] = []
    for a, b in _windows(phrases, len(x) / SR):
        part = x[int(a * SR):int(b * SR)]
        found = _recognize(part)
        fine = _align(part, [w["w"] for w in found]) if have["aligner"] and found else [None] * len(found)
        for k, (word, span) in enumerate(zip(found, fine)):
            nxt = found[k + 1]["s"] if k + 1 < len(found) else b - a
            start, end = word["s"], min(nxt, word["s"] + 0.25 + 0.09 * len(word["w"]))
            if span and abs(span[0] - start) <= 0.35:  # the two methods agree: take the finer one
                start, end = span
            words.append({"w": word["w"], "s": round(a + start, 3), "e": round(a + max(end, start + 0.05), 3)})
    return _tidy(words)


def _tidy(words: list[dict]) -> list[dict]:
    words = sorted(words, key=lambda w: w["s"])
    for w, nxt in zip(words, words[1:]):
        w["e"] = round(min(w["e"], nxt["s"]) if w["e"] > nxt["s"] else w["e"], 3)
        if w["e"] <= w["s"]:
            w["e"] = round(w["s"] + 0.02, 3)
    return words


def spread(script: str, phrases: list[list[float]]) -> list[dict]:
    """Lay a script over the phrases by syllable count. Approximate: for when nothing better is available."""
    toks = tokens_of(script)
    if not toks or not phrases:
        return []
    weight = np.array([syllables(t) for t in toks], float)
    ends = np.array([bool(re.search(r"[.,;:!?—]$", t)) for t in toks])
    length = np.array([b - a for a, b in phrases])
    n, m = len(toks), len(phrases)
    if m > n:
        phrases, length, m = phrases[:n], length[:n], n
    rate = weight.sum() / length.sum()
    cum = np.r_[0.0, np.cumsum(weight)]
    cost = np.full((m + 1, n + 1), np.inf)
    back = np.zeros((m + 1, n + 1), int)
    cost[0, 0] = 0.0
    for p in range(1, m + 1):
        for j in range(p, n - (m - p) + 1):
            i = np.arange(p - 1, j)
            c = cost[p - 1, i] + np.abs((cum[j] - cum[i]) - rate * length[p - 1])
            c = c - (0.75 if ends[j - 1] else 0.0)  # a phrase prefers to end on punctuation
            k = int(np.argmin(c))
            cost[p, j], back[p, j] = c[k], i[k]
    bounds, j = [n], n
    for p in range(m, 0, -1):
        j = back[p, j]
        bounds.append(j)
    bounds = bounds[::-1]
    words = []
    for (a, b), i, j in zip(phrases, bounds, bounds[1:]):
        share = np.r_[0.0, np.cumsum(weight[i:j])] / weight[i:j].sum()
        for k in range(i, j):
            words.append({"w": toks[k], "s": round(a + (b - a) * share[k - i], 3), "e": round(a + (b - a) * share[k - i + 1], 3)})
    return words


def align_script(x: np.ndarray, script: str, phrases: list[list[float]]) -> tuple[list[dict], bool]:
    """Times for a known script. Returns (words, approximate)."""
    toks = tokens_of(script)
    rough = spread(script, phrases)
    if not tools()["aligner"] or len(x) / SR > 300:
        return rough, True
    spans = _align(x, toks)
    if not any(spans):
        return rough, True
    words = [{"w": t, "s": None, "e": None} for t in toks]
    for w, span in zip(words, spans):
        if span:
            w["s"], w["e"] = round(span[0], 3), round(span[1], 3)
    _fill(words, len(x) / SR)
    return _tidy(words), False


def _fill(words: list[dict], total: float) -> None:
    """Give untimed words a place between their timed neighbours, by syllable count."""
    k = 0
    while k < len(words):
        if words[k]["s"] is not None:
            k += 1
            continue
        j = k
        while j < len(words) and words[j]["s"] is None:
            j += 1
        left = words[k - 1]["e"] if k else 0.0
        right = words[j]["s"] if j < len(words) else min(total, left + 0.4 * (j - k))
        share = np.r_[0.0, np.cumsum([syllables(w["w"]) for w in words[k:j]])]
        share = share / share[-1]
        for i in range(k, j):
            words[i]["s"] = round(left + (right - left) * share[i - k], 3)
            words[i]["e"] = round(left + (right - left) * share[i - k + 1], 3)
        k = j


def retext(words: list[dict], script: str) -> list[dict]:
    """Keep the measured times but show the script's words (its spelling, punctuation and capitals)."""
    toks = tokens_of(script)
    heard, wanted = [plain(w["w"]) for w in words], [plain(t) for t in toks]
    out = [{"w": t, "s": None, "e": None} for t in toks]
    for tag, i0, i1, j0, j1 in difflib.SequenceMatcher(None, heard, wanted, autojunk=False).get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i0, i1), range(j0, j1)):
                out[j]["s"], out[j]["e"] = words[i]["s"], words[i]["e"]
        elif tag == "replace" and i1 > i0 and j1 > j0:  # share the heard span among the script's words
            a, b = words[i0]["s"], words[i1 - 1]["e"]
            share = np.r_[0.0, np.cumsum([syllables(t) for t in toks[j0:j1]])]
            share = share / share[-1]
            for j in range(j0, j1):
                out[j]["s"], out[j]["e"] = round(a + (b - a) * share[j - j0], 3), round(a + (b - a) * share[j - j0 + 1], 3)
    _fill(out, words[-1]["e"] if words else 0.0)
    return _tidy(out)


def read_words(path) -> list[dict]:
    """Word times from a file: Whisper-style or plain JSON, or SRT/VTT cues (spread within each cue)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("words") or [w for seg in data.get("segments", []) for w in seg.get("words", [])]
        out = []
        for item in data:
            word = str(item.get("w", item.get("word", item.get("text", "")))).strip()
            start = item.get("s", item.get("start"))
            if word and start is not None:
                out.append({"w": word, "s": round(float(start), 3), "e": round(float(item.get("e", item.get("end", float(start) + 0.3))), 3)})
        return _tidy(out)

    def clock(stamp: str) -> float:
        parts = [float(p) for p in stamp.replace(",", ".").split(":")]
        return sum(p * 60 ** k for k, p in enumerate(reversed(parts)))

    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        match = re.search(r"([\d:.,]+)\s*-->\s*([\d:.,]+)[^\n]*\n(.+)", block, re.S)
        if match:
            a, b = clock(match.group(1)), clock(match.group(2))
            out += spread(re.sub(r"<[^>]+>", "", match.group(3)), [[a, b]])
    return _tidy(out)


def stress(db: np.ndarray, words: list[dict]) -> None:
    """Mark how hard each word is leaned on (0..1), from its level and how long it is held. Adds ``stress`` in place."""
    if not words:
        return
    peak = maximum_filter1d(db, size=5)
    level, held = [], []
    for w in words:
        a, b = int(w["s"] / HOP), max(int(w["s"] / HOP) + 1, int(w["e"] / HOP))
        level.append(float(peak[a:b].max()) if a < len(peak) else -90.0)
        held.append((w["e"] - w["s"]) / syllables(w["w"]))
    for w, lv, hd in zip(words, np.array(level), np.array(held)):
        z = 0.6 * (lv - np.median(level)) / (np.std(level) + 1e-6) + 0.4 * (hd - np.median(held)) / (np.std(held) + 1e-6)
        w["stress"] = round(float(1.0 / (1.0 + np.exp(-1.2 * z))), 2)


# ---- the whole reading ---------------------------------------------------------------------------
def analyze(path, script: str | None = None, words_file=None, pause: float = 0.35, use_model: bool = True) -> dict:
    """Read one voice recording. See the module docstring for where the word times come from."""
    x = load(path)
    if len(x) < SR // 4:
        raise VoiceError(f"{path}: no usable audio")
    db = envelope(x)
    phrases = find_phrases(db, pause)
    have = tools()
    notes: list[str] = []
    approximate = False
    if words_file:
        words, method = read_words(words_file), "imported"
        approximate = Path(words_file).suffix.lower() != ".json"
        if script:
            words = retext(words, script)
    elif use_model and have["recognizer"] and have["model"]:
        words, method = transcribe(x, phrases), "transcribed" + ("+aligned" if have["aligner"] else "")
        if script:
            words, method = retext(words, script), method + "+script"
    elif script:
        words, approximate = align_script(x, script, phrases)
        method = "spread" if approximate else "aligned"
        if approximate:
            notes.append("word times are spread across phrases by syllable count: phrase starts are measured, "
                         "words inside a phrase are estimates. `workprint voice setup` installs the aligner.")
    else:
        words, method = [], "phrases-only"
        notes.append("no words: give --script or --words, or run `workprint voice setup` to transcribe")
    stress(db, words)
    return {"rev": VOICE_REV, "duration": round(len(x) / SR, 3), "phrases": phrases, "words": words, "method": method,
            "approximate": approximate, "notes": notes}


def text_of(words: list[dict]) -> str:
    return " ".join(w["w"] for w in words)


def within(analysis: dict, start: float, end: float) -> list[dict]:
    """The words spoken between two source times."""
    return [w for w in analysis.get("words", []) if start - 0.02 <= w["s"] < end]


def placed(project, cut: dict, only: str | None = None) -> list[dict]:
    """Every word of every placed voice, in film time, tagged with the voice entry it belongs to."""
    out = []
    for item in cut.get("voice") or []:
        if "src" not in item or (only and item.get("id") != only):
            continue
        log = project.voice_log(item["src"])
        a = float(item.get("in", 0.0))
        b = a + float(item["dur"]) if item.get("dur") else float(log.get("duration", 1e9))
        for w in within(log, a, b):
            out.append({**w, "s": round(item["at"] + w["s"] - a, 3), "e": round(item["at"] + min(w["e"], b) - a, 3),
                        "voice": item.get("id")})
    return sorted(out, key=lambda w: w["s"])


def placed_phrases(project, cut: dict) -> list[list[float]]:
    """Every phrase of every placed voice, in film time."""
    out = []
    for item in cut.get("voice") or []:
        if "src" not in item:
            continue
        log = project.voice_log(item["src"])
        a = float(item.get("in", 0.0))
        b = a + float(item["dur"]) if item.get("dur") else float(log.get("duration", 1e9))
        out += [[round(item["at"] + max(s, a) - a, 3), round(item["at"] + min(e, b) - a, 3)]
                for s, e in log.get("phrases", []) if e > a + 0.05 and s < b - 0.05]
    return sorted(out)


# ---- checking excerpts as cut ---------------------------------------------------------------
PAD = 0.4            # seconds of the recording looked at either side of an excerpt
EDGE_IN, EDGE_OUT = 0.02, 0.05   # the mixer's fades on every excerpt


def _sounding(db: np.ndarray) -> np.ndarray:
    """Which 10 ms steps carry speech-level sound, judged against this stretch's own quiet and loud ends."""
    floor, top = np.percentile(db, 10), np.percentile(db, 90)
    if top - floor < 8.0:  # no contrast: all sound, or all silence
        return np.full(len(db), top > -55.0)
    return db > max(floor + 8.0, top - 24.0)


def check_placed(project, cut: dict, recognise: bool = True) -> list[dict]:
    """Each placed voice excerpt exactly as it will be cut: where its edges fall, and what a recogniser hears in it.

    Word times from a log can be wrong, most often on live recordings with a crowd, and an excerpt set from them can
    start or stop inside a word. This looks at the audio itself. ``lead`` and ``tail`` are the seconds of quiet between
    the excerpt's edges and its first and last sound; ``starts_inside`` / ``ends_inside`` mean the cut lands in
    continuous sound. With the speech model installed, ``heard`` is what the excerpt says, compared with the words
    expected of it: its captions if it has any, otherwise the words logged for that stretch.
    """
    have = tools()
    can_hear = recognise and have["recognizer"] and have["model"]
    report = []
    for item in cut.get("voice") or []:
        if "src" not in item:
            continue
        entry, log = project.voice(item["src"]), project.voice_log(item["src"])
        a = float(item.get("in", 0.0))
        dur = float(item["dur"]) if item.get("dur") else float(entry["duration"]) - a
        before = min(PAD, a)
        x = ff.read_audio(project.path_of(entry), SR, 1, a - before, before + dur + PAD)[:, 0].astype(np.float64)
        on = _sounding(envelope(x))
        i0, i1 = int(round(before / HOP)), min(len(on), int(round((before + dur) / HOP)))
        inside = np.flatnonzero(on[i0:i1])
        row = {"id": item.get("id"), "src": item["src"], "at": round(float(item["at"]), 3), "in": round(a, 3), "dur": round(dur, 3), "problems": []}
        if len(inside) == 0:
            row.update(lead=None, tail=None, starts_inside=False, ends_inside=False)
            row["problems"].append("no speech found in this excerpt")
        else:
            lead, tail = inside[0] * HOP, (i1 - i0 - 1 - inside[-1]) * HOP
            starts_inside = bool(lead < 0.03 and on[max(0, i0 - 6):i0].any())
            ends_inside = bool(tail < 0.03 and on[i1:i1 + 6].any())
            row.update(lead=round(float(lead), 2), tail=round(float(tail), 2), starts_inside=starts_inside, ends_inside=ends_inside)
            if starts_inside:
                row["problems"].append("starts inside continuous sound (a word, or loud background): the first word may be cut into, or the one before it heard")
            elif lead < 0.03:
                row["problems"].append(f"starts {lead * 1000:.0f} ms before its first sound: the start of the first word may be clipped")
            if ends_inside:
                row["problems"].append("ends inside continuous sound (a word, or loud background): the last word may be cut off, or the next one begin")
            elif tail < 0.08:
                row["problems"].append(f"ends {tail * 1000:.0f} ms after its last sound: the end of the word, or its echo, may be cut")
        said = [c for c in cut.get("captions") or [] if c.get("voice") == item.get("id")]
        if said:
            expected, source = " ".join(str(c.get("text", "")).replace("|", " ") for c in sorted(said, key=lambda c: c["at"])).split(), "captions"
        else:
            expected, source = [w["w"] for w in within(log, a, a + dur)], "log"
        row.update(expected=" ".join(expected), expected_from=source, heard=None, missing=[], extra=[])
        if can_hear:
            part = x[int(before * SR):int((before + dur) * SR)].copy()
            k_in, k_out = int(EDGE_IN * SR), int(EDGE_OUT * SR)
            if len(part) > k_in + k_out:
                part[:k_in] *= np.linspace(0.0, 1.0, k_in)
                part[-k_out:] *= np.linspace(1.0, 0.0, k_out)
            heard = [w["w"] for w in _recognize(part)]
            row["heard"] = " ".join(heard)
            if expected:
                import difflib
                want, got = [plain(w) for w in expected], [plain(w) for w in heard]
                # A log's own word times can be a little out, so against a log the first and last word are not held to it.
                slack = 1 if source == "log" else 0
                for op, a0, a1, b0, b1 in difflib.SequenceMatcher(None, want, got, autojunk=False).get_opcodes():
                    if op in ("delete", "replace"):
                        row["missing"] += [expected[i] for i in range(a0, a1) if plain(expected[i]) and slack <= i < len(expected) - slack]
                    if op in ("insert", "replace"):
                        row["extra"] += [heard[i] for i in range(b0, b1) if plain(heard[i]) and slack <= i < len(heard) - slack]
                if row["missing"] or row["extra"]:
                    row["problems"].append("the words differ from the " + source + ": not heard "
                                           + (", ".join(repr(w) for w in row["missing"]) or "nothing") + "; heard instead "
                                           + (", ".join(repr(w) for w in row["extra"]) or "nothing"))
        report.append(row)
    return report

