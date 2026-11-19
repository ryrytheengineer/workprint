# Revision commands

Every command saves a new version of the cut with a message, validates it, and prints
how many chunks the next render must redo. `workprint history` lists versions,
`workprint diff` shows what changed, `workprint undo` steps back (as a new version).

| Note from the user | Command |
|---|---|
| "Use a different shot there" | `workprint replace c012 --shot A004-07` (optionally `--in 12.5`) |
| "Start that shot a little later" | `workprint slip c012 0.4` (footage moves, the slot does not) |
| "That cut is late / early" | `workprint roll c012 --by -0.08`, or `--to 14.5 --snap 1` to land on the nearest beat |
| "Hold on that shot longer" | `workprint remove c013` (the slot before it extends), or `roll` the next cut later |
| "Cut that section faster" | `workprint insert --at 15.25 --shot A002-03` for each new cut point |
| "Swap those two" | `workprint swap c004 c009` |
| "Move the ending later / make it longer" | `workprint shift --from 30.0 --by 2.0` (then re-check music sync) |
| "Warmer / darker / less contrast" | `workprint set look 'grade={"temperature": 0.1, "exposure": -0.2}'` |
| "Push in on that one" | `workprint set c012 'move={"zoom": [1.0, 1.1]}'` |
| "Lose the effect" | `workprint set c012 fx=` (an empty value deletes the field) |
| "Change the title" | `workprint set t001 text="NEW TITLE"` |
| "Add a hit there" | `workprint new sound at=27.4 kind=impact db=-10` |
| "Music starts too late" | `workprint set music in=136.1` (re-check sync: every cut moves against the grid) |
| "Make it 35 seconds" | `workprint set film duration=35` after removing or moving what falls beyond it |

`--snap` values for `roll`: `1` beats, `2` eighth notes, `4` sixteenths, `0.25` bar lines.

Values are JSON where that makes sense (`'move={"zoom": [1, 1.1]}'`, `at=12.5`) and
plain text otherwise (`text=NEVER THE SAME`). Quote arguments that contain spaces or braces.

After revising: `workprint render --proxy`, `workprint check`, look at the storyboard.
Only the changed chunks render; the rest of the picture is reused bit for bit.

## Voice, captions and versions

| Command | What it does |
|---|---|
| `voice add FILE [--script TEXT\|@file] [--words FILE]` | Read a recording: phrases, words, times |
| `voice show [V01]` | Print what was read |
| `voice place V01 --at T [--phrase N-M \| --from A --to B] [--gain dB]` | Put it in the film; first word at T |
| `captions [--voice v001] --style line\|word\|split [--punch w,w:2] [--accent]` | Make cues from the placed voice |
| `new caption at=T text="..." [style=punch] [dur=S]` | Add a cue by hand |
| `set k004 text=... dur=... style=...` / `remove k004` | Change or delete a cue; the same for `v001` |
| `reframe --aspect 9:16 [--slots c003,c004] [--redo]` | Propose per-shot framing for a version |
| `set c004 focus_9x16=[x,y]` | Correct one shot's framing |
| `render --aspect 9:16` | Render the version |

## Sound, effects and finishing (0.3)

| Command | What it does |
|---|---|
| `set v001 treat=clear\|hall\|radio\|none` | Treat a placed voice |
| `set audio carve_db=-8` | Make room for speech in the music's mid band only |
| `voice throw v001 --word WORD[:n] [--beats 0.5] [--repeats 3]` | Echo a word in time with the music |
| `roll c014 --on kick\|snare\|hat` | Move a cut onto the nearest drum hit |
| `set c009 fx='[{"name":"xray-scan","deep":true}]'` | X-ray effects (also `xray`, `xray-pulse`, `xray-flicker`) |
| `intercut c012 --shot ID [--every 2] [--from S] [--to S]` / `--off` | Flicker a slot to a second shot |
| `set c005 speed=[2,0.5] ramp=inout interp=blend` | Eased ramp, smooth slow motion |
| `endcard --text "A\|B" [--logo F] [--wordmark F] [--tint] [--dur 3]` | Closing card with title and logos |
| `matte setup [--yes]` | Install the optional cut-out model |
| `set k004 set='{"behind": true}'` | Put a caption behind the subject |
| `still FILE [--dur 4] [--move drift\|push\|parallax]` | Turn a photograph into footage |

| `new hud kind=track\|counter\|rail at=T dur=S ...` / `set h001 ...` / `remove h001` | Instrument overlays (0.4) |
| `set v001 treat=restore` | Noise reduction for an old recording (0.4) |
