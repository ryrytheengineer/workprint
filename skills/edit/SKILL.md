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
6. **Check.** `workprint check` reports cuts that land inside a word, captions that have drifted
   off the voice, run outside the safe area, or sit on picture of similar brightness.

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
