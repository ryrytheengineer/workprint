#!/usr/bin/env python3
"""Launcher for Workprint inside a Claude Code plugin (or a plain checkout).

It keeps Workprint's Python dependencies in a private virtual environment so that
nothing is installed into the user's own Python, then runs the command line from
the source tree next to this file. Standard library only, so it runs before
anything is installed.

    WORKPRINT_HOME      where the environment lives (default: ~/.workprint)
    WORKPRINT_NO_VENV   set to 1 to run with the current interpreter instead
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ["numpy>=1.24", "scipy>=1.10", "opencv-python-headless>=4.8", "Pillow>=10.0"]


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_environment(home: Path) -> Path:
    venv = home / "venv"
    stamp = home / "venv.stamp"
    want = hashlib.sha1("\n".join(REQUIREMENTS + [sys.version.split()[0]]).encode()).hexdigest()
    python = venv_python(venv)
    if python.exists() and stamp.exists() and stamp.read_text().strip() == want:
        return python
    print(f"workprint: preparing its Python environment in {venv} (first run only)...", file=sys.stderr)
    home.mkdir(parents=True, exist_ok=True)
    if venv.exists():
        shutil.rmtree(venv)
    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "venv", "--quiet", "--python", sys.executable, str(venv)], check=True)
        subprocess.run([uv, "pip", "install", "--quiet", "--python", str(python), *REQUIREMENTS], check=True)
    else:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *REQUIREMENTS], check=True)
    stamp.write_text(want)
    return python


def main() -> int:
    if sys.version_info < (3, 10):
        print("workprint needs Python 3.10 or newer; this is " + sys.version.split()[0], file=sys.stderr)
        return 2
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if os.environ.get("WORKPRINT_NO_VENV") == "1":
        python = Path(sys.executable)
    else:
        try:
            python = ensure_environment(Path(os.environ.get("WORKPRINT_HOME") or Path.home() / ".workprint"))
        except subprocess.CalledProcessError as exc:
            print(f"workprint: could not prepare the environment ({exc}). Check your network connection, or install "
                  f"the packages yourself ({', '.join(REQUIREMENTS)}) and set WORKPRINT_NO_VENV=1.", file=sys.stderr)
            return 2
    return subprocess.call([str(python), "-m", "workprint", *sys.argv[1:]], env=env)


if __name__ == "__main__":
    sys.exit(main())
