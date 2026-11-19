# Third-party software and assets

Everything Workprint depends on, how it is used, and what its licence requires.
"Used at run time" means the user installs it and Workprint calls it; nothing in
that category is copied into this repository. Licences were checked on 2026-11-18
(sources in `research/01-ecosystem.md`).

## Required

| Component | Source | Licence | Purpose in Workprint | How it is used | Notices / restrictions |
|---|---|---|---|---|---|
| FFmpeg (`ffmpeg`, `ffprobe`) | https://ffmpeg.org | LGPL-2.1-or-later or GPL-2.0-or-later, depending on the build | Decoding, encoding (H.264/AAC), scaling, loudness measurement, joining files | Run as a separate program the user installs; never bundled, linked or modified | None for this repository. Users are bound by the licence of the build they install. H.264 and AAC may be subject to patent licensing in some jurisdictions and uses |
| NumPy | https://pypi.org/project/numpy/ | BSD-3-Clause | Arrays for frames and audio; the music analysis | Installed as a dependency; unmodified | None beyond its licence |
| SciPy | https://pypi.org/project/scipy/ | BSD-3-Clause | Filters and running min/mean in the mixer and sound synthesis | Installed as a dependency; unmodified | None beyond its licence |
| OpenCV (`opencv-python-headless`) | https://pypi.org/project/opencv-python-headless/ | Apache-2.0 (OpenCV); MIT (the wheel packaging) | Colour conversion, histograms, phase correlation, resampling in the compositor | Installed as a dependency; unmodified | The wheels bundle their own FFmpeg libraries (LGPL), which Workprint does not call |
| Pillow | https://pypi.org/project/pillow/ | MIT-CMU (HPND) | Text rendering for titles, contact sheets | Installed as a dependency; unmodified | None beyond its licence |

## Optional

| Component | Source | Licence | Purpose | How it is used |
|---|---|---|---|---|
| OpenTimelineIO | https://pypi.org/project/OpenTimelineIO/ | Apache-2.0 | Writing `.otio` timelines | Imported only when `workprint export --otio` is run and the package is installed |
| uv | https://github.com/astral-sh/uv | Apache-2.0 / MIT | Faster creation of the private environment | Used by the launcher if it happens to be on PATH; otherwise the standard library's `venv` and `pip` |
| pytest | https://pypi.org/project/pytest/ | MIT | Running the test suite | Development only |

Voice tools, installed only by `workprint voice setup --yes` and never bundled:

- **PocketSphinx** (Carnegie Mellon University and contributors), BSD-style licence, with its
  bundled US English acoustic model. Used for forced alignment of known words to audio.
- **sherpa-onnx** (the k2-fsa project), Apache-2.0. Runs the speech model.
- **Parakeet TDT 0.6b v2** speech-recognition weights by NVIDIA, CC BY 4.0, in the ONNX export
  published by the sherpa-onnx project. Downloaded from that project's GitHub releases and
  used only if its SHA-256 matches the value pinned in `src/workprint/voice.py`. NVIDIA does
  not endorse Workprint.

Matte tools, installed only by `workprint matte setup --yes` and never bundled:

- **ONNX Runtime** (Microsoft), MIT.
- **IS-Net general-use** salient-object weights from the DIS project (Xuebin Qin and
  colleagues), in the ONNX file published in the rembg project's GitHub releases.
  Downloaded from there and used only if its SHA-256 matches the value pinned in
  `src/workprint/matte.py`. Check those projects for the weights' licence terms before
  commercial use; Workprint does not redistribute them.

SVG logos are drawn by whichever of librsvg, resvg, Inkscape, ImageMagick or cairosvg is
already installed; none is bundled or installed by Workprint.

## Bundled

| Asset | Source | Licence | Modified | Where | Required notice |
|---|---|---|---|---|---|
| Archivo Black (Regular) | https://github.com/google/fonts/tree/main/ofl/archivoblack | SIL Open Font License 1.1 | No | `src/workprint/fonts/ArchivoBlack-Regular.ttf` | Licence text shipped as `ArchivoBlack-OFL.txt` |
| Instrument Serif (Regular) | https://github.com/google/fonts/tree/main/ofl/instrumentserif | SIL Open Font License 1.1 | No | `src/workprint/fonts/InstrumentSerif-Regular.ttf` | `InstrumentSerif-OFL.txt` |
| Instrument Serif (Italic) | https://github.com/Instrument/instrument-serif, taken from the `@fontsource/instrument-serif` 5.3.0 npm package | SIL Open Font License 1.1 | Container only: converted from WOFF2 to TrueType, outlines unchanged | `src/workprint/fonts/InstrumentSerif-Italic.ttf` | `InstrumentSerif-OFL.txt` |
| Inter (variable) | https://github.com/google/fonts/tree/main/ofl/inter | SIL Open Font License 1.1 | No | `src/workprint/fonts/Inter-Variable.ttf` | `Inter-OFL.txt` |

The OFL permits bundling and redistribution with software, forbids selling the fonts
by themselves, and requires the licence and copyright notice to travel with them.

## Media used for the example film (not in this repository's source tree)

The example in `examples/return/` was cut from NASA footage (public domain, as recorded
on Wikimedia Commons) and the track "Stormfront" by Kevin MacLeod (incompetech.com),
licensed under Creative Commons Attribution 3.0. Each source file, its Commons page,
author and licence are listed in `examples/return/SOURCES.json`. The source footage is
not redistributed here; the manifest lists where each file came from.
NASA material is used without any implication of NASA endorsement, and no NASA insignia was added.

## What is not here

No source code from any other project is included in this repository. Published
algorithms that Workprint implements itself are cited where they are implemented
(`src/workprint/music.py`, `src/workprint/shots.py`). Projects that were studied and
not used, and why, are listed in `research/01-ecosystem.md` and `research/03-prior-art.md`.
