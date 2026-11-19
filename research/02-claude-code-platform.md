# Claude Code as a platform

Read on 2026-11-18 from the official documentation at `code.claude.com/docs`:
[plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference.md),
[marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference.md).
Checked locally with Claude Code 2.1.328 (`claude plugin validate`).

## What the documentation establishes

- A plugin is a directory. The manifest `.claude-plugin/plugin.json` is optional; `name` is its only
  required key. Skills live in `skills/<name>/SKILL.md`, agents in `agents/`, hooks in
  `hooks/hooks.json`. The docs say to prefer `skills/` over `commands/` for new plugins.
- Components are namespaced by plugin name: this plugin's skills are `/workprint:edit` and `/workprint:setup`.
- `${CLAUDE_PLUGIN_ROOT}` (the installed plugin directory) and `${CLAUDE_PLUGIN_DATA}` are substituted
  inline in skill bodies. They are **not** present in the environment of commands Claude runs with
  the Bash tool, so a skill must write the reference into the command text itself.
- `${CLAUDE_PLUGIN_ROOT}` changes on every plugin update, so state must not be written there.
- Files in a top-level `bin/` directory are added to the Bash tool's `PATH`, but the docs state that
  claude.ai and Cowork do not install a plugin that has that directory.
- A marketplace is a repository with `.claude-plugin/marketplace.json` (`name`, `owner.name`, `plugins[]`).
  A plugin entry's `source` may be a relative path inside the same repository. Certain marketplace
  names are reserved (anything passing as Anthropic's own; `npm`, `pip`, `uv`, `github`, and others).
- `claude plugin validate <path>` is the authoritative check.

## Decisions that follow

| Decision | Reason |
|---|---|
| One repository is both the plugin and its marketplace (`"source": "./"`) | One `marketplace add` and one `install`; nothing else to host |
| No `bin/` directory; skills call `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workprint.py"` | Keeps the plugin installable on every Claude surface the docs mention |
| The launcher uses only the standard library and builds its own virtual environment | A plugin cannot assume any Python package is present |
| The environment lives in `~/.workprint`, not in the plugin directory | The plugin directory is replaced on update; the launcher cannot see `${CLAUDE_PLUGIN_DATA}` from a Bash command |
| Two skills (`setup`, `edit`) with reference files loaded on demand | Keeps the always-loaded text short; detail is read when the step needs it |
| No hooks, no MCP server, no subagents in 0.1 | Nothing in the workflow needs them yet; each would add a permission surface |

`claude plugin validate .` reports: validation passed, with nothing to report from the plugin directory checks.
A local `claude plugin marketplace add` and `claude plugin install workprint@motion-and-matter` both succeeded.

## Not verified

Installation from a published GitHub repository through `/plugin marketplace add` has not been
exercised, because the repository is not published yet. Loading from a local directory and manifest
validation were exercised. See `06-measurements.md`.
