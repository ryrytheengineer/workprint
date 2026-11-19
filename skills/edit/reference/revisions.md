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
