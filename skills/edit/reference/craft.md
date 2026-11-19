# Editorial craft, as things you can do and check

Workprint cannot supply taste. These are the working rules it is built around, each
tied to something concrete in the tool. Sources for the ideas are listed in
`research/04-editorial-craft.md` in the repository.

## Shape before shots

Decide what the film does over its length before choosing a single clip. A short
music-driven film usually has three or four movements: an opening that establishes a
world and withholds, a build that adds information and pressure, a release where the
strongest material lands, and an ending that leaves one image or one line behind.
Write these as `sections` in the structure with an `energy` from 0 to 1.
The music has usually made this decision already: put the film's release on the
track's drop (`workprint music` lists them) by choosing `music_in`.

## Pacing is contrast, not speed

Fast cutting only feels fast after something slow. Give quiet sections long slots
(`every` of 4 to 8 beats) so the release (`every` of 1, 0.5) has something to push
against. Accelerate into a turn with a list, for example `"every": [4, 2, 1]`.
After the peak, one long shot does more than another burst.
`check` reports median, shortest and longest shot; if they are close together, the
film has one gear.

## Cut on the music, and break the rule deliberately

Most cuts belong on a beat, the important ones on a bar line or a hit. `draft` puts
every cut on the grid. Then move a few on purpose: a cut a frame or two before the
beat makes the beat land on the new image rather than on the cut. `roll --by -0.04`
does that; `check` will list it as off-grid, which is the record that it was intended.

## Choose shots for what they do

- An opening shot should make the viewer ask a question; a closing shot should answer one.
- Match movement across a cut: left-to-right into left-to-right, push-in into push-in.
  The shot log's `camera` and `motion` numbers say how much a shot moves, the filmstrip says which way.
- Alternate scale. Wide, then detail, then wide reads as rhythm; five mediums in a row reads as a list.
- In quiet sections prefer steady shots and start them in their calm stretch; in loud
  sections start a shot just before its peak of motion. `draft` does this from the log;
  check it on the storyboard.
- Hold back the best image. Pin it (`pins`) to the release.

## Continuity of light and colour

A cut between very different exposures is a jolt; use that on a hit, avoid it in a
quiet passage. `cuts.jpg` shows both sides of every cut side by side. One film-wide
`look` keeps mixed sources together; per-shot `grade` fixes the outliers.
Start from no look, or a restrained preset, and add only what the picture asks for.

## Restraint

A hard cut is the default and is almost always right. A dissolve means time passing or
one idea melting into another; a dip to black is a full stop. An effect is a single
accent on a single moment. If you cannot say what an effect or a sound is for, remove it.
Negative space counts: black, silence, a held frame.

## Sound and picture

The sharpest tool is taking sound away: a beat of near silence before a drop
(`music.automation` can pull the bed down), then the hit. Designed sounds
(`impact`, `riser`, `downlifter`, `whoosh`, `swell`, `tick`, `boom`) are tuned to the
track's key; use different ones for different moments, never the same hit six times.
Target loudness is set in `audio.target_lufs` (default -14 LUFS for online delivery).

## Typography

Type is part of the picture, not a label on it. One short line, set large or set
small, never medium; inside the 5% margins (`check` warns otherwise); on a card or on a
calm, dark part of the frame; cut on with the music rather than faded when the film is hard-edged.

## The first cut is a question

Render early at proxy size, read the storyboard as a stranger would, and change it.
The useful questions: where did my eye go first, what did I learn in each section,
which shot would I miss least, does the ending follow from the opening.
