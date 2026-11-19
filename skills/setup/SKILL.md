---
name: setup
description: Check or install what Workprint needs (FFmpeg and its Python environment). Use when Workprint has just been installed, when a workprint command fails with a missing tool or module, or when the user asks whether their machine is ready.
---

# Workprint setup

Run the check:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workprint.py" doctor
```

(`python` instead of `python3` on Windows.)

The first run creates a private Python environment in `~/.workprint/venv` and installs
four packages into it (NumPy, SciPy, OpenCV headless, Pillow; about 200 MB, a minute or
two). Nothing is installed into the user's own Python. Tell the user this is happening
before the first run, because it downloads from PyPI.

Then read the output:

- **`missing ffmpeg` / `missing ffprobe`**: FFmpeg is the one thing Workprint cannot
  install for the user. Give them the command the doctor printed for their system
  (`brew install ffmpeg` on macOS, `winget install Gyan.FFmpeg` on Windows,
  `sudo apt install ffmpeg` on Debian/Ubuntu) and ask before running it yourself.
- **`missing encoder libx264`**: their FFmpeg was built without H.264. The standard
  builds from the commands above include it.
- **Python older than 3.10**: ask them to install a current Python from python.org or
  their package manager.
- **`optional opentimelineio not installed`**: only needed for `.otio` export. Install it
  only if they ask for that export.

When the last line says `ready`, say so and offer to start a film with the
`workprint:edit` skill. Needs: a folder of video clips, usually a music track, and a brief.

No GPU, no API keys and no accounts are involved. Everything runs on the user's machine.
