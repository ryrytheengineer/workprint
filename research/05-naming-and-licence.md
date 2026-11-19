# Name and licence

## Name: Workprint

A workprint is the copy of a film an editor actually cuts: rough, marked up, re-spliced
many times, and replaced by the finished print at the end. That is what this tool
produces and what it is for.

Checked on 2026-11-18:

| Where | Result |
|---|---|
| PyPI `workprint` | Not registered (HTTP 404 from `pypi.org/pypi/workprint/json`) |
| npm `workprint` | Not registered (HTTP 404 from `registry.npmjs.org/workprint`) |
| GitHub repositories named "workprint" | 25, all small. The closest in subject: `sixteenmillimeter/WORKPRINT` (2 stars, a 16 mm cut-list generator, last pushed 2023) and `cslou/workprint` (0 stars, described as a filmmaking workspace in development) |
| Claude Code reserved plugin names | Not reserved; `claude plugin validate` accepts it |

Other candidates checked and set aside: `trimbin` (an existing rough-cut editor uses the name),
`firstcut` (taken on PyPI), `roughcut` (taken on npm), `cutprint`, `kinoglyph`, `answerprint` (free but weaker names).

Not checked: trademark registers. Do that before any commercial use of the name.

## Licence: Apache-2.0

- Every required dependency is permissively licensed (BSD-3-Clause, MIT, HPND, Apache-2.0), all compatible with Apache-2.0.
- FFmpeg is run as a separate program installed by the user and is not distributed with Workprint, so its LGPL/GPL terms do not attach to this repository.
- Apache-2.0 adds an explicit patent grant, which matters for a tool a studio and its clients will rely on.
- The bundled fonts are under the SIL Open Font License 1.1, which permits bundling with software; their licence texts ship with them.
- Nothing GPL-, non-commercial- or source-available-licensed is included or required.
