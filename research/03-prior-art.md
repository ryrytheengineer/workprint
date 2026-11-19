# Prior art and where Workprint differs

Found with GitHub repository search on 2026-11-18 ("claude code video editing", "claude video
editor skill") and read at README level only. No code, prompts or skill text from these projects
was read for implementation or copied; this is a description of what each says it does.

| Project (licence, stars on 2026-11-18) | What its README says it does | Overlap with Workprint |
|---|---|---|
| [browser-use/video-use](https://github.com/browser-use/video-use) (MIT, 31k) | Edits raw takes with an agent: removes filler words and dead air, grades, burns subtitles, generates animation overlays, self-evaluates at cut boundaries. Setup asks for an ElevenLabs API key. | An agent that edits footage and checks its output. Aimed at speech-led content; cuts follow the transcript. |
| [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) (Apache-2.0, 21k) | Makes product promos by capturing the user's web pages and animating them with Remotion from a library of motion recipes, cut to the beat. States it is "not a video generator". | Music-aware promos, but drawn from screenshots rather than cut from footage. |
| [kajisho5/ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) (MIT, 8k) | A local toolbox of ffmpeg operations for agents (probe, cut, fit, caption, export, check). | General-purpose operations; no editorial model of a film. |
| [barefootford/buttercut](https://github.com/barefootford/buttercut) (custom licence, 626) | A Ruby tool and agent that builds selects and rough cuts and writes editing-application XML; targets Apple Silicon Macs; uses WhisperX. | Rough cuts for finishing in an NLE, driven by transcripts. |
| [talsiach/take-one](https://github.com/talsiach/take-one) (MIT, 368) | Makes launch videos, ads and music videos from a one-line idea. Needs Node and Chrome; tested on macOS only. | Finished films, but generated rather than cut from the user's footage. |
| [ChatCut-Inc/agent-plugin](https://github.com/ChatCut-Inc/agent-plugin) (Apache-2.0, 1k) | Plugin and MCP server for a commercial AI video editor. | Hosted product; different model. |
| [samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp) (MIT, 4k) | Lets an agent drive DaVinci Resolve. | Requires the application; Workprint must work without one. |

## The gap

None of the projects above takes a folder of footage and a music track and cuts a
music-driven film from them as an editor would, on a laptop, without an editing application
or an API key. That is Workprint's whole scope. Specifically:

1. **Footage-first, music-driven.** The primary structure is the music's bar grid and energy, not a transcript.
2. **A shot log built by looking.** Shots are found inside every clip, measured, shown on contact
   sheets, and described and rated by the editor before anything is cut.
3. **A slot-based cut file** anchored to the timeline, with stable ids, history and named revision operations.
4. **A renderer that reuses work.** Content-addressed chunks; untouched picture is bit-identical across versions.
5. **A checker that measures the file**: re-detected cuts against the plan, cut points against the beat grid, loudness, safe areas.
6. **Style profiles as measurements**, not as a claim to have learned taste.
7. **Nothing to sign up for.** No keys, no GPU, no hosted service; four Python packages and FFmpeg.

## Overlap that remains, stated plainly

- Self-checking a render at cut boundaries is also something video-use's README describes. Workprint's
  checker was designed from its own requirements (compare re-detected cuts with the manifest; measure
  against the beat grid) and shares no code or text with it.
- Cutting to the beat is common to several projects. Workprint's beat tracking is its own implementation
  of published methods (cited in `music.py`).
- Workprint does nothing for talking-head content today. For that, the projects above are the better tools.
