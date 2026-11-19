"""Project state on disk.

A Workprint project is a plain directory. Source media is referenced in place and
never modified; everything Workprint writes lives inside the project directory.

    workprint.json    sources, music, output format
    brief.md          the creative brief, verbatim
    log/shots.json    the shot log (measured facts + the editor's notes)
    log/music.json    tempo, beats, bars, sections of the music
    cut.json          the current cut (the edit manifest)
    history/          every saved version of the cut, with a message
    renders/          rendered films
    review/           storyboards and check reports per version
    cache/            render chunks and mixes; safe to delete
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import __version__, ff

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mxf", ".mts", ".m2ts", ".ogv"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".aif", ".aiff", ".opus"}


class ProjectError(RuntimeError):
    pass


def signature(path: Path) -> str:
    """Content fingerprint that is cheap on large media: size plus the first and last megabyte."""
    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.sha1(str(size).encode())
    with open(path, "rb") as fh:
        digest.update(fh.read(1 << 20))
        if size > (2 << 20):
            fh.seek(size - (1 << 20))
            digest.update(fh.read(1 << 20))
    return digest.hexdigest()[:16]


def read_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise ProjectError(f"missing {path.name}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data, compact_lists: tuple[str, ...] = ()) -> None:
    """Write JSON that stays readable: entries of the named top-level lists get one line each."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not compact_lists:
        text = json.dumps(data, indent=1, ensure_ascii=False)
    else:
        parts = []
        for key, value in data.items():
            if key in compact_lists and isinstance(value, list) and value:
                rows = ",\n".join("  " + json.dumps(row, ensure_ascii=False) for row in value)
                parts.append(f" {json.dumps(key)}: [\n{rows}\n ]")
            else:
                parts.append(f" {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}")
        text = "{\n" + ",\n".join(parts) + "\n}"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.file = self.root / "workprint.json"
        if not self.file.exists():
            raise ProjectError(f"{self.root} is not a Workprint project (no workprint.json). Run `workprint init`.")
        self.data = read_json(self.file)

    # ---- layout -------------------------------------------------------------
    @property
    def log_dir(self) -> Path:
        return self.root / "log"

    @property
    def cache_dir(self) -> Path:
        path = self.root / "cache"
        path.mkdir(exist_ok=True)
        return path

    @property
    def cut_file(self) -> Path:
        return self.root / "cut.json"

    @property
    def format(self) -> dict:
        return self.data["format"]

    def save(self) -> None:
        write_json(self.file, self.data, compact_lists=("sources",))

    # ---- creation -----------------------------------------------------------
    @classmethod
    def create(cls, root, footage: list[str | Path], music=None, width=1920, height=1080, fps=24.0, name=None, brief=None) -> "Project":
        root = Path(root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        if (root / "workprint.json").exists():
            raise ProjectError(f"{root} already holds a project")
        data = {"workprint": __version__, "name": name or root.name,
                "format": {"width": int(width), "height": int(height), "fps": float(fps)}, "sources": [], "music": None}
        write_json(root / "workprint.json", data)
        project = cls(root)
        project.add_footage(footage)
        if music:
            project.set_music(music)
        if brief:
            (root / "brief.md").write_text(brief.strip() + "\n", encoding="utf-8")
        project.save()
        return project

    def _store_path(self, path: Path) -> str:
        """Keep paths relative when the media sits inside the project, absolute otherwise."""
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path.resolve())

    def add_footage(self, items: list[str | Path]) -> list[dict]:
        files: list[Path] = []
        for item in items:
            item = Path(item).expanduser()
            if item.is_dir():
                files += sorted(p for p in item.rglob("*") if p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."))
            elif item.is_file():
                files.append(item)
            else:
                raise ProjectError(f"footage not found: {item}")
        known = {s["sig"] for s in self.data["sources"]}
        added = []
        for path in files:
            sig = signature(path)
            if sig in known:
                continue
            info = ff.probe(path)
            if not info.get("has_video"):
                continue
            entry = {"id": f"A{len(self.data['sources']) + 1:03d}", "path": self._store_path(path), "sig": sig,
                     "duration": round(info.get("video_duration") or info["duration"], 3), "fps": info["fps"],
                     "width": info["width"], "height": info["height"], "has_audio": info["has_audio"],
                     "matrix": ff.color_matrix(info)}
            self.data["sources"].append(entry)
            known.add(sig)
            added.append(entry)
        return added

    def set_music(self, path) -> dict:
        path = Path(path).expanduser()
        info = ff.probe(path)
        if not info.get("has_audio"):
            raise ProjectError(f"no audio stream in {path}")
        self.data["music"] = {"path": self._store_path(path), "sig": signature(path), "duration": round(info["duration"], 3)}
        return self.data["music"]

    def add_voice(self, path) -> dict:
        path = Path(path).expanduser()
        info = ff.probe(path)
        if not info.get("has_audio"):
            raise ProjectError(f"no audio stream in {path}")
        voices = self.data.setdefault("voices", [])
        sig = signature(path)
        for entry in voices:
            if entry["sig"] == sig:
                return entry
        entry = {"id": f"V{len(voices) + 1:02d}", "path": self._store_path(path), "sig": sig, "duration": round(info["duration"], 3)}
        voices.append(entry)
        return entry

    def voice(self, voice_id: str) -> dict:
        for entry in self.data.get("voices", []):
            if entry["id"] == voice_id:
                return entry
        raise ProjectError(f"unknown voice {voice_id!r}")

    def voice_log(self, voice_id: str) -> dict:
        return read_json(self.log_dir / f"voice-{voice_id}.json", {}) or {}

    # ---- lookups ------------------------------------------------------------
    def source(self, source_id: str) -> dict:
        for src in self.data["sources"]:
            if src["id"] == source_id:
                return src
        raise ProjectError(f"unknown source {source_id!r}")

    def path_of(self, entry: dict) -> Path:
        path = Path(entry["path"])
        return path if path.is_absolute() else self.root / path

    def music_path(self) -> Path | None:
        return self.path_of(self.data["music"]) if self.data.get("music") else None

    # ---- logs ---------------------------------------------------------------
    def shots(self) -> list[dict]:
        return read_json(self.log_dir / "shots.json", {"shots": []})["shots"]

    def save_shots(self, shots: list[dict]) -> None:
        write_json(self.log_dir / "shots.json", {"workprint": __version__, "shots": shots}, compact_lists=("shots",))

    def music(self) -> dict | None:
        path = self.log_dir / "music.json"
        return read_json(path) if path.exists() else None

    # ---- the cut and its history -------------------------------------------
    def cut(self) -> dict:
        return read_json(self.cut_file)

    def history(self) -> list[dict]:
        return read_json(self.root / "history" / "index.json", {"versions": []})["versions"]

    def version(self) -> int:
        versions = self.history()
        return versions[-1]["n"] if versions else 0

    def save_cut(self, cut: dict, message: str) -> int:
        """Save the cut as the current version and append it to history."""
        from .manifest import dump  # local import: manifest depends on project helpers
        versions = self.history()
        n = (versions[-1]["n"] + 1) if versions else 1
        dump(cut, self.cut_file)
        dump(cut, self.root / "history" / f"{n:04d}.json")
        versions.append({"n": n, "saved": time.strftime("%Y-%m-%d %H:%M:%S"), "message": message})
        write_json(self.root / "history" / "index.json", {"versions": versions}, compact_lists=("versions",))
        return n

    def load_version(self, n: int) -> dict:
        return read_json(self.root / "history" / f"{n:04d}.json")
