# Changelog

## 0.6.0 (2026-11-19)

- `workprint screen find|make`: play a clip on a screen in a still image (a television, a
  monitor, a phone). The picture is bent to the screen's corners, rounded and bowed like
  glass, given a tube or flat-panel look, lights what is round it, and the camera pushes in.
- `workprint cutout`: a subject cut out of a clip on a plain card, with large and small
  words appearing behind them at set times (needs the matte tools).
- Thirteen more designed sounds: `screen-on`, `static`, `key`, `shutter`, `rocket`, `blast`,
  `beep`, `reverse`, `clang`, `glitch`, `heartbeat`, `whip`, `hum`.
- `workprint voice check`: looks at every placed voice excerpt as it will actually be cut.
  Flags an excerpt that starts or ends inside sound or too close to it, and, with the
  speech model, prints what the excerpt says and how that differs from its captions.
- An italic cut of the bundled serif (`font: serif-italic`).

## 0.5.0 (2026-11-19)

- Matte transition (`"t": {"type": "matte"}`): the next shot opens through, or behind,
  the outgoing subject.
- Caption entrances (`pop`, `grow`, `slide`, `rise`, `drop`).
- `workprint match`: colour-match one slot to another.
- `workprint loop`, `workprint cover`, `workprint deliver`.
- `workprint reframe --follow`: a version's frame can travel during a shot.

## 0.4.0 (2026-11-19)

- HUD overlays (`hud` list, `workprint new hud`): tracking brackets, box or reticle with
  label and live readout; counters in fixed-width figures; a frame rail with timecode.
- Noise reduction for voice recordings (`treat=restore`, or `denoise` in a treatment).

## 0.3.0 (2026-11-19)

- Voice treatment (`treat`: clear, hall, radio), a speech-band carve in the music
  (`audio.carve_db`), echo throws (`workprint voice throw`), and a measured
  voice-over-music level in `workprint check`.
- Drum hits by kind (kick, snare, hat) in the music log; structure sections (`"on"`) and
  `roll --on` can land cuts on them.
- Effects: `xray-scan`, `xray-pulse`, `xray-flicker` and x-ray options (`tint`, `deep`,
  `positive`); `workprint intercut` flickers a slot to a second shot; `ramp` eases speed
  changes and `interp` (`blend`, `flow`) makes slow motion smooth.
- Logos: titles can be images (PNG, SVG); `workprint endcard` lays out a closing card.
- Optional mattes (`workprint matte setup`): captions and titles can sit behind the
  subject; `workprint still` turns a photograph into a shot (push, drift, parallax).
- Cuts made with 0.1 and 0.2 keep their cached chunks.

## 0.2.0 (2026-11-19)

- Voice: `workprint voice add|show|place|setup`. Phrases and pauses are measured directly;
  word times come from an optional local speech model re-timed by a forced aligner, from a
  script, or from a Whisper-style JSON, SRT or VTT file. The model is downloaded only on
  request and only used if its checksum matches.
- Captions: `workprint captions` and a `captions` list in the cut. Styles `line`, `word`,
  `split` and `punch`; words are revealed without the line moving; `--accent` adds a
  different designed hit under each punch word, tuned to the track's key.
- Voice-led cutting: a structure section with `"follow": "voice"` cuts just ahead of each
  phrase and holds through it. The checker reports cuts inside words and captions that
  have drifted off the voice.
- Versions: `workprint reframe --aspect 9:16|4:5|1:1` proposes per-shot framing with a
  review sheet; `workprint render --aspect` renders the version through its own cache.
- Fixed: the mix could turn to noise at full scale when a voice was present (a rounding
  error in the ducking envelope). Mixes are rebuilt.
- The automated test workflow file is not in the repository yet.

## 0.1.0 (2026-11-18)

First release.

- Project setup, shot detection with per-shot measurements, contact sheets and filmstrips.
- Music analysis: tempo, beats, bar lines, per-bar energy, sections, drops, accents, key.
- The cut format: timeline-anchored slots with ids, validation and version history.
- First assembly from an editorial structure on the beat grid, with a reason recorded per shot.
- Renderer: reframing, camera moves, speed and speed ramps, grade, look (grain, vignette, letterbox),
  six frame effects, cut/dissolve/dip/flash, title cards and typography; content-addressed chunk cache.
- Mix: music bed with automation, voice with ducking, clip sound, eight synthesised designed sounds,
  loudness-targeted master with a look-ahead limiter.
- Check: re-detected cuts against the plan, cut points against the beat grid, loudness, black and frozen
  picture, title safe areas, footage reuse; storyboard and cut-pair sheets.
- Revision commands: replace, slip, roll, insert, remove, swap, shift, set, new, undo.
- Style profiles measured from reference films.
- Experimental EDL and OpenTimelineIO export.
- Claude Code plugin with `edit` and `setup` skills and a self-installing launcher.
