---
name: edit
description: Cut a film from footage, music and a creative brief, or revise a film cut earlier. Use when the user gives video clips (and usually a music track) and asks for an edit, a cut, a trailer, a spec film, a launch film or a music-driven sequence, or asks to change one that Workprint made.
---

# Workprint: cutting a film

You are the editor. Workprint is your cutting room: it measures footage and music,
renders exactly what a cut file says, checks the result, and re-renders only what
you change. The judgement is yours: what the film is about, which shots earn a
place, where it breathes and where it hits.

Run every command through the launcher, from the project directory or with `-p`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workprint.py" -p <project-dir> <command> ...
```

(`python` instead of `python3` on Windows.) Below this is written as `workprint <command>`.
If a command reports something missing, run the `workprint:setup` skill first.

## The loop

1. **Set up the project.** One directory per film, outside the footage folder.
   `workprint init <project-dir> --footage <files or folders> --music <track> --size 1920x1080 --fps 24 --brief "<the user's brief, verbatim>"`
   Source media is referenced where it is and never modified.

2. **Look at the footage before deciding anything.**
   `workprint ingest` finds every shot in every clip (clips often contain several) and
   writes contact sheets to `log/sheets/`. **Read every sheet image.** Then record what
   you saw: write a JSON file mapping shot ids to `{"desc": ..., "tags": [...], "rating": 0-5}`
   and run `workprint log apply notes.json`. Rate 0 to exclude a shot (slates, bars, soft
   focus, burned-in text), 4-5 for shots the film should be built around. Use
   `workprint look <shot>` for a filmstrip when one frame is not enough to judge a shot,
   especially for long shots and anything you plan to feature (`--from 30 --to 60` looks at
   part of a long shot; `workprint frame <source> <seconds>` saves one full-size frame). A filename is not a
   description; never log a shot you have not looked at.

3. **Listen to the music through its measurements.**
   `workprint music` prints tempo, bar lines, sections with their energy, and drops.
   Decide where in the track the film starts (`music_in`) so that the track's turning
   points land where the film needs them. Bar-line confidence below about 0.3 means the
   downbeat guess may be off by a beat: check the first strong hit against `drops`.

4. **Decide the shape, then write it down as a structure.** Read
   `reference/craft.md` now. Write `structure.json`: the sections of the film, how hard
   each hits (`energy` 0-1), how often it cuts (`every`, in beats), tags to favour or
   avoid, the few shots you pin to exact moments, the end card. Then
   `workprint draft structure.json` lays the cuts on the beat grid and fills the slots,
   noting why it chose each shot. Format details: `reference/cut-format.md`.

5. **Render, check, and look.**
   `workprint render --proxy` (half size, fast) then `workprint check`. The check
   re-detects cuts in the rendered file, measures how cuts sit on the musical grid,
   measures loudness, and writes `review/<render>/storyboard.jpg` and `cuts.jpg`.
   **Read both images.** The storyboard is the film on one page; `cuts.jpg` shows both
   sides of every cut. Fix every `[warn]`, and treat an "unplanned picture change" as a
   source clip's own cut hiding inside your slot.

6. **Revise in place.** The draft is a starting point. Expect to replace a third of it.
   Use the revision commands in `reference/revisions.md` (`replace`, `slip`, `roll`,
   `swap`, `insert`, `remove`, `shift`, `set`, `new`). Each saves a new version and tells
   you how little has to re-render. Never rebuild the cut from the structure to make a
   local change: that throws away every decision made since.

7. **Deliver.** `workprint render` (full size), `workprint check`, read the storyboard
   once more, then give the user the file in `renders/`, a short account of the shape of
   the film and the decisions that mattered, and anything the check still flags.
   `workprint export --edl cut.edl` (or `--otio`) if they want to finish in an editing application.

## When there is a voice

A voice-over changes what the film is cut to. Do this after step 3, before you write the structure.

1. **Read it.** `workprint voice add FILE` prints the phrases, every word with its time, and the
   words the speaker leans on. If the voice tools are missing, ask the user before running
   `workprint voice setup --yes`: it is a one-time 482 MB download of a speech model that runs on
   their machine. Without it, pass `--script "the words"` or `--words file.json`. If word times
   come back marked approximate, say so and prefer `line` and `split` captions to `word` and `punch`.
2. **Do not trust the transcript blindly.** You cannot hear the recording. If the user gave you the
   words, pass them with `--script` so their spelling and punctuation are used. Show the user what
   was heard, especially on old or noisy recordings.
3. **Place it against the music.** `workprint voice place V01 --at T` puts the first word at film
   time T; `--phrase 2-3` or `--from/--to` uses part of the recording, and several lines are several
   placements. Put the words that matter on a bar line or just after a hit. A line over a drop fights it.
4. **Let the picture follow where the voice leads.** Copy the placements into the structure's
   `"voice"` list and mark those sections `"follow": "voice"`: cuts land just ahead of each phrase and
   none interrupts one. Where the music leads, leave it off and the cuts stay on the beat.
5. **Set the words.** `workprint captions --style line|word|split` makes cues from the placed voice.
   `--punch word,word:2` sets chosen words full-frame; `--accent` puts a different hit under each.
   Choose punch words for meaning, rarely more than one a sentence: the "leaned on" list measures level,
   not sense. Re-run after moving a voice. Fix a cue with `workprint set k004 text=...` or `dur=...`,
   move it with `set k004 set='{"pos":[0.5,0.3]}'`, `remove k004`, or add one by hand:
   `workprint new caption at=3 text="..." style=punch`.
6. **Check the excerpts as cut.** `workprint voice check` looks at each placed excerpt in the recording itself:
   how much quiet lies between its edges and its first and last sound, and whether it starts or ends inside
   continuous sound. With the speech model it also prints what each excerpt says. Run it after every change to
   a placement, and read `heard` against the words you meant to use: word times in a log can be most of a
   second out on a live recording, and an excerpt set from them can hold the wrong words. Leave 80 ms or more
   before the first word and run on into the silence after the last, so a word's end and its echo survive.
7. **Check.** `workprint check` reports cuts that land inside a word, captions that have drifted
   off the voice, run outside the safe area, or sit on picture of similar brightness.

## Sound, effects and finishing

Use these when the brief or the user asks for them, not by default. Each is one field or command.

- **A voice that is hard to follow.** `workprint check` prints how many dB the voice sits over the music.
  Under about 6 dB, try `workprint set audio carve_db=-8` (the music gives way only in the speech band),
  `workprint set v001 treat=clear`, or more `gain_db`. `treat=hall` adds a large room for weight;
  `treat=radio` narrows it like an old broadcast. You cannot hear the result: say so, and ask the user to listen.
- **A word that should ring.** `workprint voice throw v001 --word will` repeats it into the gap after it, in time
  with the music. It needs a gap: do not throw a word in the middle of a sentence.
- **Cuts on the drums.** `workprint music` lists kick, snare and hat hits. A structure section with
  `"on": "kick"` moves each grid cut onto the nearest one; `workprint roll c014 --on snare` does it for one cut.
  On dense or orchestral music the kick list is unreliable: prefer the beat grid there.
- **X-ray.** `fx` entries `xray`, `xray-scan` (a line crosses and leaves x-ray behind it; `width` makes it a
  moving band, `dir` right/left/down/up), `xray-pulse` (hits as x-ray and settles) and `xray-flicker`. Options on
  all: `tint`, `deep` (more contrast and glow), `positive` (for dark footage, which plain x-ray turns white).
- **Flicker between two shots.** `workprint intercut c012 --shot A004-07 --every 2 --from 0.5`. Short runs
  (1 to 3 frames) read as a flicker; use it at one moment, not across a section.
- **Speed.** `speed` [from, to] with `ramp` (linear, in, out, inout) eases the change; `interp` `blend` or
  `flow` makes slow motion smooth instead of stepped. Check the result on a filmstrip: both can smear.
- **Instruments.** `workprint new hud kind=track at=12 dur=2.5 box='[x,y,w,h]' label="..."` draws brackets
  that follow what is in the box (fractions of the frame, read off a frame you have looked at); `style=box|reticle`,
  `readout=true`. `kind=counter from=0 to=3900 suffix=" HRS"` runs a number; `kind=rail label=... timecode=true`
  frames the picture. Keep a track inside one shot and on a subject with clear detail; check a frame near its end.
- **An old or noisy recording.** `workprint set v001 treat=restore` reduces steady hiss and hum. It needs pauses in
  the recording to learn the noise from. You cannot hear whether it thinned the voice: ask the user to listen.
- **Through the subject.** `workprint set c007 t='{"type":"matte","frames":14}'` opens the new shot from inside
  the outgoing shot's subject; `"style":"hold"` brings it in behind a subject that lingers. `"pin"` holds the subject
  whole over the new shot, then cuts; `"lead"` brings the new subject in first, over the old shot. `"fly-in"` and
  `"fly-out"` fly a cut-out straight in or off, `"spin-in"` and `"spin-out"` turn it as it goes (`"spin": -1` for the
  other side), and `"flash": 3` brings the new background in with a flash. Needs the matte tools. Use it once or
  twice, out of a shot with one clear subject, and look at three frames of it.
- **The white box.** `workprint set c012 box=true` shows a shot as a box on a plain field. It slams in unless the
  shot before was boxed; `box='{"out":true}'` grows it out. Use it for a run of a few shots, not a whole section.
- **Details, one frame each.** `fx` `details` lights single details of a shot for a frame: `spots` with `frame`, a
  `box` round the detail (fractions of the frame, read off a frame you have looked at), `mode` (`fill`, `invert`,
  `outline`) and `key` or `seed` to pick the piece. The key finds tones, not objects: look at every flash frame.
- **Bars that open.** `workprint set look letterbox_until=15.6` holds the letterbox until that second (a drop),
  then opens the frame.
- **Type that moves.** `workprint captions ... --enter pop|grow|slide|rise|drop`, or `set k004 set='{"in":"pop"}'`.
- **Matching shots.** `workprint match c004 --to c001` when footage from different sources should sit together
  (archive beside modern, two cameras). Compare frames afterwards; lower `--amount` if it overshoots.
- **End card.** `workprint endcard --text "LINE ONE|LINE TWO" --logo mark.svg --wordmark word.svg [--tint]`.
  Use the brand's own files, supplied by the user; do not redraw a logo.
- **Words behind the subject.** `workprint set k004 set='{"behind": true}'` (titles: `style.behind`). Needs
  `workprint matte setup --yes` (ask first: 179 MB). It costs over a second a frame and guesses the subject, so
  use it on one or two strong shots with a clear subject, and look at the frame.
- **A clip on a screen.** For a still with a television, monitor or phone in it: `workprint screen find still.jpg`
  guesses the screen and draws its outline on a review image. Look at it. Correct `--corners "x,y x,y x,y x,y"`
  (top-left, clockwise, in pixels of the still), `--radius` and `--bow` and run find again until the red line sits
  on the edge of the glass. Then `workprint screen make still.jpg --corners ... --clip A003 --in 49.2 --dur 2.7`
  writes the shot and adds it to the footage. `--look crt|flat|none`; `--push 1.0,1.7` is the camera's start and end
  magnification; `--crop` shows part of the clip; `--neutral 0.8` removes colour the old picture cast on the casing.
  Pair it with the sounds `screen-on`, `hum` and `static`. Use the user's still; a soft or small one goes soft as
  the camera closes in, so keep `--push` modest on anything under about 2000 pixels wide.
- **A cut-out card.** `workprint cutout --clip A009 --in 208.2 --dur 2.6 --small "Life can't just be about"
  --big "SOLVING|PROBLEMS." --times 0.15,0.47,...` sets the subject of that clip on a plain card with the words
  behind them. One time per word, small words first; or `--voice V03` to take them from a voice log (then check
  them: see the voice check). `--place right|left|centre`, `--ignore x0,y0,x1,y1` to drop a logo from the matte.
  Needs the matte tools. Use it for the one or two lines that carry the film, on a subject who stands clear of
  their background, and look at a frame from the start, middle and end.
- **More sounds.** Beside the hits and risers: `screen-on`, `static`, `key` (one per appearing word), `shutter`
  (fast cuts), `rocket` and `hum` (beds; take `dur`), `blast`, `beep`, `reverse` (air rushing up to a cut; takes
  `dur`), `clang`, `glitch`, `heartbeat` (bars where the music drops out), `whip` (cuts between cards). You have
  not heard any of them: place them where the picture gives a reason, keep the small ones 10 dB or more under
  the hits, and tell the user the sound design is unheard.
- **A photograph as a shot.** `workprint still photo.jpg --dur 4 --move drift|push|parallax`, then `ingest`.
  `parallax` needs the matte tools; keep it for photos with one clear subject.

## Finishing for posting

After the cut is approved: `workprint loop` (the end dissolves back into the opening, for players that repeat),
`workprint cover [--at T]` (look at the frame it picks; choose your own with `--at` if another says more) and
`workprint deliver [--mbps 10]` (a smaller upload file). Each works on the latest render, or on a file you name.
For the tall version, `workprint reframe --aspect 9:16 --follow` lets the frame travel during a shot whose
subject crosses the picture.

## Other shapes

For a 9:16, 4:5 or 1:1 version of a finished cut, run `workprint reframe --aspect 9:16`. It proposes
where each shot sits in the new frame and writes `review/reframe-9x16.jpg`. Read the sheet: the
proposal follows detail and movement, not meaning, and it will miss subjects. Correct with
`workprint set c004 focus_9x16=[0.3,0.5]` (0 is left or top, 1 is right or bottom), then
`workprint render --aspect 9:16` and `workprint check` that file. Captions and titles lay themselves
out again for the new frame; the 16:9 film and its cache are untouched.

## When the user asks for a change

Translate the note into the smallest set of revision commands, apply them, render,
check, look at the affected part of the storyboard, and report what changed.
"The intro feels rushed" is a pacing note about a section (fewer, longer slots: `remove`
cuts or `roll` them later), not a request for a new film. "Replace the third shot" is
`replace c003 --shot <id>` after looking at candidates in the shot log. "Move the reveal
six seconds later" is a `shift` or a re-pin, and then a check of music sync, because the
music does not move with the picture. Keep everything the user did not mention.

## Standards

- Every cut either lands on the grid or is off it on purpose. `check` lists the ones that are off.
- No slot may cross a cut inside its source. `validate` warns; fix it with `slip` or `replace`.
- Do not reuse a shot unless the repetition is the idea.
- Effects (`punch`, `rgbsplit`, `invert`, `xray`, `shake`) and designed sounds are accents.
  If more than a few slots carry one, the film is leaning on them.
- Typography is minimal by default: one idea per card, generous margins.
- Say what you could not judge. You cannot hear the mix or watch motion; the loudness
  numbers and still frames are evidence, not the experience. Ask the user to watch and listen.

## Learning the user's taste

If the user points to films they like, `workprint profile ref1.mp4 ref2.mp4 -o profile.json`
measures shot lengths, cutting rate over time, how often cuts land on the beat, loudness
and letterbox. Show them the summary, let them correct the `preferences` block, and pass
`--profile profile.json` to `draft`. It captures habits, not judgement; say so.
