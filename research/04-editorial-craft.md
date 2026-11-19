# Editorial craft, turned into capabilities

"Make it cinematic" is not an instruction a program can follow or a test can check.
This note records the principles the tool is built around, where they come from, and
the concrete thing each became. The sources are standard texts on editing; nothing here
is quoted from them.

| Principle | Source | What it became in Workprint |
|---|---|---|
| A cut should serve emotion and story before continuity; rhythm is a criterion in its own right | Walter Murch, *In the Blink of an Eye* (the "rule of six") | Sections carry an `energy` and an intent; the skill asks for the shape of the film before any shot is chosen; `check` reports pacing per film, not just errors |
| Meaning arises between shots, not inside them | Lev Kuleshov's experiments; V. I. Pudovkin, *Film Technique* | The storyboard and `cuts.jpg` show shots in sequence and both sides of every cut, because a shot cannot be judged alone |
| Cutting can follow absolute length, the content's movement, or its tone | Sergei Eisenstein, *Film Form* (metric, rhythmic and tonal montage) | Cut points on a beat grid (`every`), in-points chosen from each shot's motion curve (calm stretch vs peak), a film-wide `look` with per-shot `grade` |
| Pace is felt through contrast | Karel Reisz and Gavin Millar, *The Technique of Film Editing* | Accelerating rates (`"every": [4, 2, 1]`); `check` reports shortest, median and longest shot so a one-gear film is visible |
| Cut on movement; match direction and screen position | Edward Dmytryk, *On Film Editing* | Per-shot `motion` and `camera` measurements, filmstrips to see direction, `move` to continue a push across a cut |
| Sound changes what the picture means; a sound and an image that coincide fuse | Michel Chion, *Audio-Vision* (added value, synchresis) | Cuts and designed sounds placed on the same grid; sounds tuned to the track's key; `check` measures cut-to-beat distance in milliseconds |
| Loudness has delivery norms | EBU R 128 / ITU-R BS.1770 | The mix is mastered to a loudness target with a true-peak ceiling and measured after rendering |
| Text must be legible and inside a safe area | Broadcast title-safe practice | `check` warns when a title leaves the 5% margin or sits on picture of similar brightness |

## What was deliberately left out

- No library of transition presets. A hard cut is the default; dissolve, dip and flash exist because each means something.
- No automatic "style". Looks are a handful of restrained starting points and every value is editable.
- No claim to judge shot quality. The engine measures; the rating comes from the editor after looking.

## Known limits of the approach

The editor in this system sees still frames and numbers. It cannot watch motion at speed or
hear the mix. Motion and camera measurements, filmstrips and loudness meters reduce that gap;
they do not close it. The skill tells the editor to say so and to ask the person to watch and listen.
