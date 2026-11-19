# Roadmap

Ordered by how much each item would improve a first cut. Nothing here is implemented
unless the README says so.

## Next (0.2)

1. **Voice, further.** 0.2 reads one voice-over in English. Next: an example film cut to a
   voice, other languages, more than one speaker, dialogue and interview material, and a
   wider test set than one recording.
2. **Better bar lines.** The downbeat guess is the weakest measurement. Add an optional
   neural beat/downbeat tracker and let the editor nudge the bar phase by hand.
3. **Speed that looks good.** Frame blending or optical-flow interpolation for slow
   motion; eased speed ramps; reverse.
4. **Verified timeline export.** Round-trip the EDL and OTIO output through Premiere Pro
   and DaVinci Resolve and fix what does not survive; add FCPXML.
5. **Tested macOS and Windows installs** in continuous integration, plus a published
   package so `pipx install workprint` works outside Claude Code.

## After that

6. **Mattes.** Optional SAM 2 integration for subject mattes: cut-out holds across a
   cut, text behind a subject, selective grades.
7. **Match-cut search.** Rank pairs of shots by similarity of shape, position and
   motion so the planner can propose match cuts instead of leaving them to luck.
8. **Better reframing.** 0.2 proposes a fixed frame per shot from detail and movement.
   Next: a frame that follows the subject through the shot.
9. **Colour.** A scene-referred float pipeline, 10-bit output, HDR sources tone-mapped
   on ingest, LUT import, and automatic shot-to-shot balance as a starting point.
10. **Stems.** Optional Demucs separation so cuts can follow drums alone and the mix
    can duck individual stems.
11. **A logging subagent** so large libraries (hundreds of shots) are described in
    parallel rather than one sheet at a time.
12. **Multi-camera and sync-sound** material.

## Explicitly not planned

- A hosted service or anything that needs an account or API key for the core workflow.
- Generative video. Workprint cuts footage that exists.
- A template or preset marketplace.
