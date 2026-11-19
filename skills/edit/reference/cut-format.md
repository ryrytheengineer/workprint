# File formats

Everything is plain JSON inside the project directory. You may edit `cut.json` by hand
(then run `workprint validate` and save through a revision command), but the revision
commands are safer because they keep history.

## structure.json (input to `workprint draft`)

```json
{
  "title": "Working title",
  "duration": 40.0,
  "music_in": 137.8,
  "sections": [
    {"name": "quiet", "from": 0.0,  "to": 13.7, "energy": 0.2, "every": 8, "tags": ["wide"], "avoid": ["flare"], "move": "push"},
    {"name": "build", "from": 13.7, "to": 27.4, "energy": 0.6, "every": [4, 2]},
    {"name": "drop",  "from": 27.4, "to": 37.0, "energy": 1.0, "every": 1}
  ],
  "pins": [{"at": 27.4, "shot": "A004-07", "in": 12.2}],
  "end_card": {"dur": 3.0, "text": "TITLE", "style": {"font": "display", "size": 0.16}},
  "look": {"preset": "steel", "grain": 0.03, "letterbox": 2.39},
  "sounds": [{"at": 27.4, "kind": "impact", "db": -10}],
  "audio": {"target_lufs": -14}
}
```

- `from`/`to`, `at`: film time in seconds. Film time `t` plays music time `t + music_in`.
  Put section boundaries on bar lines: film time = bar time from `workprint music` minus `music_in`.
- `every`: beats between cuts. 4 is one bar in 4/4, 1 a beat, 0.5 an eighth note. A list
  splits the section into equal parts with those rates in order.
- `energy` (0-1) is matched against how lively each logged shot is, and decides whether a
  shot starts in its calm stretch or at its motion peak.
- `tags` favour shots carrying any of them; `avoid` excludes shots carrying any.
- `pins` force a shot at a time (and always create a cut there). `in` is optional.
- `move: "push"` adds a slow 5% push-in to slots of 1.5 s or longer in that section.

## cut.json (the edit)

```json
{
  "format": {"width": 1920, "height": 1080, "fps": 24},
  "duration": 40.0,
  "music": {"in": 137.8, "gain_db": 0, "fade_in": 0, "fade_out": 1.5, "automation": [[26.9, 0], [27.3, -30], [27.4, 0]]},
  "look": {"preset": "steel", "grade": {"contrast": 1.05}, "grain": 0.03, "vignette": 0.2, "letterbox": 2.39},
  "cuts": [
    {"id": "c001", "at": 0.0, "src": "A003", "in": 14.2, "shot": "A003-02", "note": "why this shot"},
    {"id": "c002", "at": 3.43, "src": "A001", "in": 2.0, "speed": [1.0, 0.5], "move": {"zoom": [1.0, 1.08], "x": [0.5, 0.45], "ease": "inout"},
     "grade": {"exposure": 0.3}, "fx": ["punch"], "t": {"type": "dissolve", "frames": 8}},
    {"id": "card", "at": 37.0, "card": {"bg": "#000000"}}
  ],
  "titles": [{"id": "t001", "at": 37.2, "dur": 2.6, "text": "TITLE", "style": {"font": "display", "size": 0.16, "tracking": 0.02}, "fade": [0, 0.4]}],
  "sounds": [{"id": "s001", "at": 27.4, "kind": "impact", "db": -10}],
  "voice":  [{"file": "vo/line1.wav", "at": 2.0, "gain_db": 0}],
  "audio": {"target_lufs": -14, "ceiling_db": -1, "duck_db": -6}
}
```

**Cuts are slots.** Each entry starts at `at` and fills the frame until the next entry
starts (the last runs to `duration`). `src` + `in` say which source and where in it
(seconds). Replacing footage never moves a cut point.

| Field | Meaning |
|---|---|
| `speed` | `1.0` normal, `0.5` half speed, `[2.0, 1.0]` a linear ramp across the slot |
| `move` | `zoom` `[from, to]` (1.0 = full frame), `x`/`y` `[from, to]` centre of the view (0-1), `ease` `linear`/`in`/`out`/`inout` |
| `fit`, `focus` | `fit: "contain"` shows the whole source with black bars; `focus: [x, y]` chooses what a cover crop keeps |
| `grade` | `exposure` (stops), `contrast`, `saturation`, `temperature`, `tint`, `lift`, `gamma`, `gain`, `fade` |
| `fx` | `punch`, `rgbsplit`, `invert`, `xray`, `mono`, `shake`; as a string, or `{"name": "xray", "from": 0, "to": 6}` in frames |
| `t` | transition into the slot: `cut` (default), `{"type": "dissolve", "frames": 8}`, `dip`, `flash` |
| `freeze` | `true` holds the in-point frame for the whole slot |
| `nat` | level in dB of the clip's own sound (omitted = silent) |
| `card` | a plain colour instead of footage: `{"bg": "#000000"}` |

Looks: presets `none`, `steel`, `print`, `bleach`, `noir`; any `grade` keys override the preset.
Title `style`: `font` (`display`, `serif`, `sans`, or a path to a font file), `size` (fraction of
frame height), `tracking`, `leading`, `color`, `pos` `[x, y]`, `align`, `width`, `upper`, `shadow`, `opacity`.
Sounds: `kind` from `impact`, `sub`, `riser`, `downlifter`, `whoosh`, `swell`, `tick`, `boom`; `db`; optional
`dur` for the four moving ones; or `{"file": "path.wav", "at": ..., "db": ...}` for the user's own sound.

## log/shots.json and log/music.json

Written by `ingest` and `music`. Per shot: `start`, `end`, `dur` (seconds in the source),
`motion` and `camera` (how much the picture and the frame move), `luma`, `contrast`,
`sat`, `peak` and `calm` (where the liveliest moment and the steadiest stretch begin),
and your `desc`, `tags`, `rating`. Music: `tempo`, `beats`, `bars`, `sections`, `drops`, `hits`, `key`.

## Voice and captions

In `structure.json` and `cut.json`, `voice` places recordings on the timeline:

    "voice": [{"id": "v001", "src": "V01", "at": 11.88, "in": 0.0, "dur": 5.59, "gain_db": 0}]

`src` is a project voice (`workprint voice add`); `at` is where the excerpt starts in the film,
`in` and `dur` select part of the recording. Music ducks under speech by `audio.duck_db` (default -6).
A structure section with `"follow": "voice"` cuts on phrase starts (see the edit skill).

`captions` holds the words on the picture:

    "captions": [{"id": "k003", "at": 12.0, "dur": 2.3, "text": "American industrial", "style": "split",
                  "voice": "v001", "words": [[0.04, "American"], [0.59, "industrial"]]}]

`style` is `line`, `word`, `split` or `punch`. `words` are offsets from `at`; without them the whole
text appears at once. `set` overrides style values for one cue: `font` (display, serif, sans), `size`
(fraction of frame height), `pos` ([x, y], 0..1), `color`, `case` (upper, lower, null), `width`, `shadow`,
`fade` ([in, out] seconds), `dim` (how far the picture darkens behind a punch word). In split text a `|`
chooses where the halves divide. Cues made by `workprint captions` carry `voice` and are replaced when it
runs again; cues without it are yours and are left alone.

Per-version framing lives on the cut entries: `"focus_9x16": [0.62, 0.5]`.

## log/voice-V01.json

`phrases` ([start, end] in recording time), `words` ({w, s, e, stress}), `method` (how the word times
were obtained: `transcribed+aligned`, `aligned`, `spread`, `imported`, `phrases-only`) and `approximate`.

## Added in 0.3

- Voice entries: `treat` (`clear`, `hall`, `radio`, `none`, or a dict such as `{"preset": "hall", "reverb": 0.3}`)
  and `throws` (written by `workprint voice throw`). `audio.carve_db` (0 = off) lowers only the speech band of the music under a voice.
- `log/music.json` has `drums`: `{"kick": [...], "snare": [...], "hat": [...]}` in music time. Structure sections accept `"on": "kick"`.
- Cut entries: `ramp` (`linear`, `in`, `out`, `inout`), `interp` (`nearest`, `blend`, `flow`),
  `intercut` (`{"src": "A004", "in": 12.0, "every": 2, "from": 0.5, "to": 1.5, "pattern": [2, 1]}`).
- `fx` names `xray-scan`, `xray-pulse`, `xray-flicker`; x-ray options `tint`, `detail`, `deep`, `positive`;
  scan options `dir`, `width`, `ease`; flicker options `every`, `pattern`.
- Titles may carry `image` (PNG or SVG path, relative to the project) instead of `text`, with `style`
  `width` or `height`, `pos`, `align`, `opacity`, `color` (redraw a one-colour logo in that colour).
- `behind: true` in a caption's `set` or a title's `style` draws it behind the subject.

## Added in 0.4

- `hud` list: `{"id": "h001", "kind": "track", "at": 12.0, "dur": 2.5, "box": [x, y, w, h], "label": "...", "readout": true, "style": "corners|box|reticle"}`,
  `{"kind": "counter", "from": 0, "to": 3900, "decimals": 0, "prefix": "", "suffix": " HRS", "pos": [0.08, 0.9], "scale": 1.6, "ease": "linear"}`,
  `{"kind": "rail", "label": "...", "timecode": true, "margin": 0.055}`. All accept `color`, `opacity`, `size`, `weight`.
- Voice `treat`: `restore`, or `denoise` (0..1) inside a treatment dict.

## Added in 0.5

- Transition `"t": {"type": "matte", "frames": 14, "style": "through"|"hold"}` (needs the matte tools).
- Caption `set`: `"in"` (`pop`, `grow`, `slide`, `rise`, `drop`) and `"in_dur"` (seconds, default 0.14).
- Cut entries: `match` (`{"from": [[mean], [spread]], "to": [...], "amount": 0.8, "ref": "c001"}`, written by `workprint match`)
  and `focus_9x16_to` (where a version's frame ends up; with `focus_9x16` as where it starts).
