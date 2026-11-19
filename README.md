# Workprint

**A cutting room for Claude Code.** Give Claude a folder of footage, a music track and a
brief; get back a finished film cut to the music, and an edit you can keep directing
in plain language. Changing one shot re-renders half a second of picture, not the film.

Workprint is for editors, filmmakers and creative directors who already know what a
good cut is and want the distance between an idea and a watchable first cut to be
minutes. It is not a template engine or a podcast clipper.

By [Motion & Matter](https://ryanmchargue.com/creative), an experimental creative lab. Version 0.4.0.

![Storyboard of the example film](examples/return/review/storyboard.jpg)

*"Return", 41 seconds, cut with Workprint from NASA's public-domain Artemis footage.
Preview: [`examples/return/return-preview.mp4`](examples/return/return-preview.mp4).
How it was made, shot by shot: [`examples/return/`](examples/return/).*

## What it does

- **Looks at the footage.** Finds every shot inside every clip, measures motion, camera
  movement and exposure, and lays the shots out on contact sheets. Claude reads the
  sheets and logs what is actually in each shot before anything is cut.
- **Reads the music.** Tempo, beats, bar lines, how energy moves through the track, where it drops.
- **Reads the voice.** Finds the phrases and pauses in a voice-over and the time of every
  word, transcribed on your machine by an optional local speech model or aligned from a
  script you supply. A film can then cut on the breath and land a word on a bar line.
- **Sets the words.** Captions timed to the voice in four styles: a line that builds as it
  is spoken, one word at a time, a split serif that keeps the middle of the frame clear,
  and full-frame punch words, each with a different designed hit under it.
- **Cuts on the grid.** Claude decides the shape of the film; Workprint lays the cuts on
  the beat, fills each slot with the best-fitting logged shot, and writes down why.
- **Renders the film**: reframing, push-ins, speed ramps, grade, a film-wide look,
  title cards, a mix with music, voice and designed sound, mastered to a loudness target.
- **Checks its own work.** Re-detects the cuts in the rendered file, measures each one
  against the beat, measures loudness, and catches a source clip's own cut hiding inside a shot.
- **Revises in place.** "Replace the third shot", "that cut is late", "hold the ending
  longer" become named operations on a readable cut file with full history. Only what
  changed is rendered again, and untouched picture is identical to the frame.
- **Treats the voice.** Clarity, a hall or an old-radio treatment on a voice-over; the music
  carved out only where speech needs the room; a word thrown as echoes in time with the
  track; and a measured voice-over-music level, since the editor cannot hear.
- **Cuts to the drums.** Finds kick, snare and hi-hat hits in the track and can land cuts
  on them, not just on the beat grid.
- **Has a few signature effects.** X-ray (plain, scanning, pulsing, flickering), a slot that
  flickers back and forth to a second shot, eased speed ramps and smooth slow motion.
- **Draws instruments.** Brackets or a reticle that track something through a shot with a label
  and live readout, a counter in fixed-width figures, and a frame rail with timecode.
- **Cleans an old recording.** Noise reduction for hiss and hum under a voice (`treat=restore`).
- **Closes with the brand.** An end card with a stacked title and a logo and wordmark from
  PNG or SVG files.
- **Puts words behind the subject**, and turns a photograph into a shot with depth, using an
  optional cut-out model.
- **Makes the tall version.** Re-renders a finished cut as 9:16, 4:5 or 1:1, proposes where
  each shot sits in the new frame, and gives you a sheet to correct it from.
- **Learns habits, not taste.** Point it at films you like and it measures shot lengths,
  cutting rate, how often cuts land on the beat, loudness. You correct the numbers; it uses them.

It runs on your machine. No GPU, no API keys, no accounts, no editing application. The one
large downloads are optional and explicit: a 482 MB speech model (`workprint voice setup --yes`) and a
179 MB cut-out model (`workprint matte setup --yes`).

## Install

You need [Claude Code](https://claude.com/claude-code), Python 3.10 or newer, and FFmpeg.

In Claude Code:

```
/plugin marketplace add ryrytheengineer/workprint
/plugin install workprint@motion-and-matter
```

Then ask Claude to "set up Workprint", or run `/workprint:setup`. The first run builds a private Python
environment in `~/.workprint` (four packages, about 360 MB) and tells you how to install
FFmpeg if it is missing (`brew install ffmpeg`, `winget install Gyan.FFmpeg`, `sudo apt install ffmpeg`).

Without Claude Code, from a checkout:

```
python3 scripts/workprint.py doctor        # same launcher the plugin uses
# or: pip install -e . && workprint doctor
```

## Your first film

Tell Claude what you want:

> Use Workprint. The clips are in `~/footage/robot-shoot`, the track is `~/music/pulse.mp3`.
> Cut a 45-second film: dark, industrial, aggressive. Begin quietly, build tension through
> deliberate shot selection, and land the reveal on the drop. Minimal typography, no generic transitions.

Claude sets up a project, looks at every shot, reads the music, proposes a shape, cuts,
renders a proxy, checks it, looks at the storyboard, revises, and hands you the film.
Then you direct:

> The intro feels rushed. Replace the third shot with something wider. Move the reveal one bar later.

The same steps by hand:

```
workprint init film --footage ~/footage/robot-shoot --music ~/music/pulse.mp3 --brief "..."
workprint -p film ingest                  # shots, measurements, contact sheets
workprint -p film music                   # tempo, bars, sections, drops
workprint -p film draft structure.json    # first assembly on the grid
workprint -p film render --proxy && workprint -p film check
workprint -p film replace c003 --shot A004-07
workprint -p film voice add ~/vo/line.wav            # phrases, words and when each is said
workprint -p film voice place V01 --at 12.0          # the first word lands at 12.0 s
workprint -p film captions --style split --punch genius --accent
workprint -p film reframe --aspect 9:16              # then: render --aspect 9:16
workprint -p film set v001 treat=hall && workprint -p film set audio carve_db=-8
workprint -p film voice throw v001 --word will       # echo a word into the gap after it
workprint -p film roll c014 --on kick                # land a cut on the nearest kick
workprint -p film set c009 fx='[{"name":"xray-scan"}]'
workprint -p film intercut c012 --shot A004-07 --every 2
workprint -p film new hud kind=track at=12 dur=2.5 box='[0.42,0.2,0.16,0.6]' label="SLS"
workprint -p film new hud kind=counter at=3 dur=5 from=0 to=3900 suffix=" HRS"
workprint -p film set v001 treat=restore              # noise reduction for an old recording
workprint -p film endcard --text "NEVER|THE SAME" --logo mark.svg --wordmark word.svg
workprint -p film still photo.jpg --move parallax    # a photograph becomes footage
workprint -p film render && workprint -p film check
workprint -p film export --edl film.edl   # optional hand-off to an editing application
```

(`workprint` here is `python3 scripts/workprint.py`, or the installed command.)

## How it works

Claude is the editor; Workprint is the cutting room. All judgement stays with the
editor and the person directing it. The engine is deterministic Python with no model
calls: it measures, renders exactly what the cut file says, and checks the result.

The edit is one readable JSON file of *slots*: each entry says when it starts and what
fills the frame until the next one starts. Cut points therefore belong to the timeline
and the music; replacing footage never moves a cut. The film renders as independent
chunks stored by content hash, and is assembled without re-encoding, which is why a
small change costs a small render.

More: [ARCHITECTURE.md](ARCHITECTURE.md), the file formats in
[`skills/edit/reference/cut-format.md`](skills/edit/reference/cut-format.md), the
revision commands in [`skills/edit/reference/revisions.md`](skills/edit/reference/revisions.md).

## What has been tested

Measured on one Linux machine with 2 CPU cores; details and method in
[research/06-measurements.md](research/06-measurements.md).

| | |
|---|---|
| Test suite | 57 tests, all passing: 54 on synthetic media with exact expected answers, 3 that run only where an optional tool is installed (speech model, cut-out model, SVG converter) |
| Example film | 11 clips (30 minutes of 1080p footage) to a checked 41 s film, end to end |
| Shot logging | 146 shots found in 30 minutes of footage, 4 to 6 times faster than real time |
| Render | 1080p at about 16 frames per second, 960x540 proxy at 23 to 30, 341 MB peak memory |
| A one-shot revision | 12 of 984 frames re-rendered in 2.5 s; the other 972 bit-identical |
| Music sync on the example | 26 of 26 cuts within 45 ms of a beat |
| Plugin | Validates, installs and loads with Claude Code 2.1.328, from a local checkout and from GitHub (0.1.0) |
| Voice | Five excerpts (5 to 8 s) of a 1940 radio address: the transcript matched the known text word for word; on three of them, all 8 phrase-opening words landed within 0.02 s of phrase starts measured separately from the signal level |
| Voice setup | Through the plugin launcher into a clean environment: 102 s, 1.1 GB on disk including the base environment; a 5 s clip read in 3.4 s |
| Older projects | After 0.2 and 0.3 the 0.1 example project still finds all 27 of its cached chunks: nothing re-renders |
| Sound | Treatments, carve, throws and the voice-level meter are tested by measurement (band levels, echo timing, peak ceiling), not by ear |
| Drum hits | Exact on a synthetic kit. On one real 120 BPM track: snare hits 100% and hat hits 80% on the 16th-note grid, kick hits 67% |
| Effects | X-ray variants inspected on a real frame; flicker and smooth slow motion verified frame by frame on synthetic clips |
| Noise reduction | Real speech with hiss and hum added 18 dB under it: the voice went from 19 to 39 dB above the noise floor and the transcript was unchanged. Not tested on a recording that was noisy to begin with |
| HUD | Tracker held a subject moving 117 px across synthetic frames to within 5 px; reticle, rail and counter rendered on a real shot and inspected |
| End card | Laid out and rendered with real SVG logos, inspected, passed by the checker |
| Mattes | Inspected on three real frames and one rendered shot (a word behind a rocket); about 1.6 s per matted frame on 2 CPU cores |
| Captions and versions | Four caption styles and a 9:16 re-render of a 41 s trial film, inspected frame by frame and passed by the checker. No example film ships with them yet |

## Limitations

Read these before relying on it.

- **Verified on Linux only.** It is written to be portable, but it has not been run on
  macOS or Windows yet.
- **The editor cannot watch or listen.** Claude judges from still frames, filmstrips and
  meters. Motion, performance and the feel of the mix need your eyes and ears.
- **Built for music-driven films up to a minute or two**, with or without a voice-over.
  Dialogue, interviews and more than one speaker are out of scope.
- **Voice is new and lightly tested.** Transcription and word timing were verified on a
  handful of short clips from one 1940 English recording. English only. Other voices,
  accents and noisy or music-backed recordings are unverified, so read the transcript it
  prints. Without the optional tools a script is spread across the phrases by syllable
  count, and word times inside a phrase are then estimates (it says so).
- **Which words matter is the editor's call.** The "leaned on" list is level and length,
  not meaning. Punch words and their hits are placed where you say.
- **Sound treatment has not been heard.** The voice treatments, carve and echo throws are
  verified by measurement only. Whether the hall suits the voice is for your ears.
- **Drum hits are a measurement, not stem separation.** Clear kits are found well; on dense
  or orchestral mixes the kick list is inflated. Nothing here removes a vocal from a song.
- **Smooth slow motion is approximate.** `blend` ghosts on fast movement; `flow` keeps edges
  but can smear where things cross. Look before you keep it.
- **Mattes find "the subject", not your subject.** The cut-out model guesses what the picture
  is of, softens on dark or busy footage, does not track a chosen object, and is slow.
  Parallax on stills fills what was behind the subject crudely; keep those moves small.
- **The HUD tracker follows texture, not meaning.** It holds on a clear, steady subject and
  drifts on fast, blurred or turning ones. It has been tested on synthetic motion and one
  nearly static real shot. Keep a track inside one shot.
- **Noise reduction needs pauses to learn the noise from**, handles only steady noise, and
  thins the voice if pushed. Listen to it.
- **Plain x-ray inverts the picture**, so dark footage turns white. Use `"positive": true` there.
- **Reframing is a proposal** made from detail and movement, not from recognising a
  subject. It will be wrong on some shots; the review sheet is there to be read.
- **The first assembly is a starting point.** On the example about two thirds of its
  shots were replaced before the film was right.
- **Bar lines are an estimate.** Tempo and beats are reliable on steady music; which beat
  is "one" is a heuristic with a reported confidence. Music with a changing tempo is not handled.
- **Hard cuts inside source clips are found; dissolves are not.**
- **8-bit, Rec.709.** HDR and log footage is not converted. Slow motion repeats frames (no interpolation).
- **Timeline export is experimental.** EDL and OpenTimelineIO files are written and the
  OTIO file reads back, but import into Premiere Pro and Resolve has not been verified.
  Grades, effects, titles and the mix do not travel.
- **Designed sounds are synthesised.** They are tuned to the track's key and mixed
  conservatively, and they are not a sound library. Use your own files where it matters.
- **No mattes, tracking or object removal yet.** See [ROADMAP.md](ROADMAP.md).

## Platforms and requirements

| | |
|---|---|
| Python | 3.10 or newer |
| FFmpeg | Any recent build with libx264 and AAC (tested with 6.1) |
| Python packages | NumPy, SciPy, OpenCV (headless), Pillow; installed automatically into a private environment |
| Matte tools (optional) | onnxruntime and a 179 MB cut-out model, installed only when you run `workprint matte setup --yes` |
| SVG logos (optional) | librsvg, resvg, Inkscape, ImageMagick or cairosvg; PNG logos need nothing |
| Voice tools (optional) | PocketSphinx, sherpa-onnx and a 482 MB speech model, installed only when you run `workprint voice setup --yes` |
| Hardware | No GPU. The example rendered at 1080p on 2 CPU cores, peaking at 341 MB in the largest process |
| Operating systems | Linux tested. macOS and Windows expected to work, not yet verified |

## Your footage, and other people's

Workprint never modifies or uploads source media; it reads files where they are and
writes only inside the project directory. What you may do with a film depends on your
rights to the footage and music in it. The example uses public-domain and Creative
Commons material, credited in [`examples/return/SOURCES.json`](examples/return/SOURCES.json).

## Project

- [ARCHITECTURE.md](ARCHITECTURE.md): the design and the reasons for it
- [research/](research/): what was studied, what was chosen, what was measured
- [THIRD_PARTY.md](THIRD_PARTY.md): every dependency and bundled asset, with licences
- [ROADMAP.md](ROADMAP.md): what comes next
- [CHANGELOG.md](CHANGELOG.md)

Licensed under [Apache-2.0](LICENSE). The bundled typefaces are under the SIL Open Font License.

Workprint is original software. It integrates FFmpeg, NumPy, SciPy, OpenCV and Pillow
through their public interfaces and contains no code from other editing projects.
The human brings the taste; Workprint does the cutting-room work.
