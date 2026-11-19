# Measurements

Everything here was measured on 2026-11-18 on one machine: a Linux x86-64 container with
2 CPU cores, 7 GB of RAM, no GPU, Python 3.13.18 and FFmpeg 6.1.1. Times on a current laptop
should be better; nothing here was measured on macOS or Windows.

## Tests

| What | Result |
|---|---|
| Test suite (23 tests on synthetic media with exact expected answers) | 23 passed, about 37 s |
| Same suite in the environment the launcher builds (NumPy 2.5.5, SciPy 1.18.1, OpenCV 5.1.0, Pillow 13.0.0) | Passed on every run after the fix below (three runs at 21 tests, one at the final 23) |
| Same suite on Python 3.10.20, the oldest supported version (NumPy 2.2.6, SciPy 1.15.3, OpenCV 5.1.0, Pillow 12.3.0) | 23 passed |
| One flaky run seen before that | Cause found: FFmpeg's `gradients` test source is randomly seeded. Fixed by seeding it |

The suite checks, among other things: cuts inside sources found to the frame; tempo within 1.5%,
beats within 35 ms and the drop within a beat on a synthetic track; a flat colour surviving the whole
pipeline within two code values; the mix landing within 1 LU of its loudness target under the
true-peak ceiling; voice ducking the music; a hidden source cut being reported by the checker; and frame-level bit-identity of
untouched picture after a revision.

## Installation

| What | Result |
|---|---|
| `claude plugin validate .` (Claude Code 2.1.328) | Passed |
| `claude plugin marketplace add <local checkout>` then `claude plugin install workprint@motion-and-matter` | Both succeeded; plugin listed as enabled |
| `claude plugin details workprint` | 2 skills; about 137 tokens always loaded, about 1,400 when `edit` is invoked |
| Launcher first run, building its environment with `uv` | 4.8 s, `doctor` reports ready |
| Launcher first run with only `venv` and `pip` | 7.5 s |
| Launcher later runs | 0.14 s overhead |
| Size of the private environment | 358 MB |

The install times are a lower bound: package downloads in this environment came through a fast local proxy.
**Not exercised:** installing from a published GitHub repository; any run on macOS or Windows.

## The example film ("Return", `examples/return/`)

Input: 11 clips of NASA Artemis footage, 1,795 s (29.9 minutes) of 1080p VP9, and one 334 s music track.

| Step | Result |
|---|---|
| `ingest`: find and measure shots | 146 shots. 213.6 s for the first 9 clips (1,337 s of footage) on an idle machine, 6.3 times faster than real time. 372 s for all 11 clips with another job sharing the CPU |
| Contact sheets | 14 pages, about 100 s |
| `music` | 334 s track analysed in 2.0 s: 120.14 BPM, 669 beats, 168 bars, one drop found at 207.99 s |
| `draft` | Under 1 s. 31 slots, every cut on the beat grid, no validation warnings |
| Proxy render (960x540), nothing cached | 984 frames in 32 to 42 s over three runs (23 to 30 frames per second) |
| Full render (1920x1080), nothing cached | 984 frames in 59.9 s (16.4 frames per second); 123 s when limited to one job with another task running |
| Peak memory during a full render | 341 MB in the largest process |
| Output | 19.6 MB master (H.264, CRF 20), 4.0 MB proxy; render cache 233 MB |
| `check` on the final film | PASS. 21 of 26 hard cuts re-detected in the picture, 5 reported as barely visible (dark shot to dark shot), 0 unplanned. 26 of 26 cuts within 45 ms of a beat, 16 on a bar line. -14.7 LUFS integrated, true peak -1.1 dBTP, loudness range 8.2 LU |

### Revision consistency

| Change | Re-rendered | Time | Frame comparison (`ffmpeg -f framemd5`) |
|---|---|---|---|
| Replace one half-second shot (`replace c013 ...`) | 12 of 984 frames, 1 of 27 chunks | 2.5 s | Exactly frames 490 to 501 differ; the other 972 are bit-identical |
| `undo` | 0 frames | 1.4 s | All 984 frames identical to the version before the change |
| Nine grade changes after a full proxy render | 429 of 984 frames | 22 s | not compared |

### How the cut was made

The history in `examples/return/history/index.json` is the actual record: three drafts (the second and
third after fixing planner faults listed below), then 33 revision commands to reach the intended cut
(mostly `replace`, plus `remove`, `set` and one `slip`), then grade and exposure changes prompted by
the checker and the storyboard, and finally the revision test and its undo.

About two thirds of the first assembly's shots were replaced. That is the honest measure of the
planner: it produces a film-shaped sequence on the grid in under a second, and an editor still
has to make it good. `examples/return/review/storyboard-first-assembly.jpg` and `storyboard.jpg`
show both.

## Cross-checks against known answers

| Check | Result |
|---|---|
| Beat tracker on a commercial track whose grid had been measured by hand earlier (bar = 1.7154 s, a bass entry at 169.667 s, key C# minor) | Tempo 139.77 BPM against 139.91; nearest bar line 10 ms from the hand-measured entry; key C# minor |
| Same track through librosa's default beat tracker | 136.0 BPM, so its beats drift against both the hand measurement and Workprint's |
| `profile` on a 49 s edit cut to that track | 139.79 BPM, C# minor, -14.3 LUFS (the mix had been mastered to -14.4) |

## Faults found by the real footage, and what was done

1. **False cuts in night footage.** A continuous 341 s tracking shot of the launch was split into 39
   "shots", and a continuous slow-motion shot into 4. Cause: hue is undefined for near-black pixels,
   so noise moved them between histogram bins. The detector now uses a luma/chroma histogram with an
   odd number of chroma bins and a minimum pixel change. Result: 3 shots and 1 shot. A regression test
   on synthetic dark, noisy footage was added.
2. **Colour shift.** Greys lost two code values per encode/decode pass on swscale's fast path. Accurate
   rounding is now requested explicitly in both directions; a test holds the round trip to two code values.
3. **Planner grids were anchored to the track, not the section**, so "every 8 beats" could start a bar late. Now anchored to each section's start.
4. **A missing cut at the join of two cutting rates** inside one section. Fixed.
5. **Pinned shots were being used elsewhere first.** Pinned shots now count as used from the start.
6. **Dark was treated as black.** Night shots with small lights were flagged black (and so hidden from
   the planner and warned about by the checker). Black now also requires that nothing in the frame is bright.
7. **Bitrate.** The first full render was 494 MB for 41 s (CRF 16 plus added grain). Defaults are now CRF 20
   at the `medium` preset for delivery and CRF 23 `veryfast` for proxies.
8. **A static shot reported as frozen** in a low-bitrate proxy. The frozen-picture test now requires truly repeated frames.

## What was not measured or verified

- macOS and Windows (the CI workflow is written but has not run).
- Import of the EDL and `.otio` exports into Premiere Pro or DaVinci Resolve. The `.otio` file reads back correctly with OpenTimelineIO.
- 4K sources, 10-bit or HDR sources, variable-frame-rate phone footage, projects longer than about a minute, source audio (`nat`) and voice-over on real material (covered by synthetic tests only).
- The film itself as moving picture and sound. It was assembled and judged from still frames and meters. Whether it is a good film is for a person watching it to say.
