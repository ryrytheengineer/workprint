# Changelog

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
