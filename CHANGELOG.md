# Changelog

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
