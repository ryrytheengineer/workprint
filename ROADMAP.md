# Roadmap

Ordered by how much each item would improve a first cut. Nothing here is implemented
unless the README says so.

## Next (0.2)

1. **Voice, further.** 0.2 reads one voice-over in English. Next: an example film cut to a
   voice, other languages, more than one speaker, dialogue and interview material, and a
   wider test set than one recording.
2. **Better bar lines.** The downbeat guess is the weakest measurement. Add an optional
   neural beat/downbeat tracker and let the editor nudge the bar phase by hand.
3. **Speed, further.** 0.3 has eased ramps, blended and motion-interpolated slow motion.
   Next: reverse, and interpolation that handles crossing motion.
4. **Verified timeline export.** Round-trip the EDL and OTIO output through Premiere Pro
   and DaVinci Resolve and fix what does not survive; add FCPXML.
5. **Tested macOS and Windows installs** in continuous integration, plus a published
   package so `pipx install workprint` works outside Claude Code.

## After that

5a. **Made frames, further.** 0.6 puts a clip on a screen in a still and makes cut-out cards.
   Next: a screen in a moving shot (tracked corners), things passing in front of the screen,
   photo stacks and picture tiles on a card, and a finder that is right more often.

6. **Mattes, further.** 0.3 has text behind a subject from a salient-object model. Next:
   choosing and tracking a particular subject (SAM 2), cut-out holds across a cut,
   selective grades.
7. **Match-cut search.** Rank pairs of shots by similarity of shape, position and
   motion so the planner can propose match cuts instead of leaving them to luck.
8. **Better reframing.** 0.2 proposes a fixed frame per shot from detail and movement.
   Next: a frame that follows the subject through the shot.
9. **Colour.** Moved up: original camera footage (for example S-Log3 from a Sony FX3) needs it.
   First, log and HDR ingest: read the transfer from the file, convert with a camera LUT or a
   named transform to Rec.709, and warn when a source looks like log. Then a scene-referred float
   pipeline, 10-bit output and automatic shot-to-shot balance as a starting point.
10. **Stems.** 0.3 finds drum hits by measurement. Real separation (Demucs or similar), so a
    vocal can be removed from under a voice-over and stems ducked individually, is still to do.
11. **A logging subagent** so large libraries (hundreds of shots) are described in
    parallel rather than one sheet at a time.
12. **Multi-camera and sync-sound** material.

## Explicitly not planned

- A hosted service or anything that needs an account or API key for the core workflow.
- Generative video. Workprint cuts footage that exists.
- A template or preset marketplace.
