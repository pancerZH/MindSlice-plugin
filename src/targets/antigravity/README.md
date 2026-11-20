# MindSlice for Antigravity

Portable, human-readable long-term memory for Antigravity (the `agy` CLI and the Antigravity app), packaged
from [MindSlice](https://github.com/pancerZH/MindSlice): memory is plain Markdown cards in a folder you choose,
the user's standing memory (persona, reply language, standing rules) reaches every conversation, and changes
to it wait for your approval.

## Install

```bash
git clone https://github.com/pancerZH/MindSlice-plugin
agy plugin install MindSlice-plugin/plugins/antigravity
```

The plugin is installed disabled, because it needs two settings. Open `/plugin` in `agy` (or the plugin's
page on the Customizations page of the Antigravity app), turn **mindslice** on and fill them in:

- **Memory workspace**: the absolute path of a folder. An existing MindSlice workspace (a folder with
  `mounts.toml`) is used as is; a new path or an empty folder is initialized as a new workspace; a folder that
  already holds other files is refused, and nothing is written to it.
- **Review every write**: `false`, or `true` to send every change the agent makes to staging for your approval
  (recommended for small local models).

Start a new conversation, then run `/mindslice:setup` to seed the memory and verify that it reaches the model.
To update, pull the repository and run the same `agy plugin install` again; your settings are kept. On
Windows, exit running `agy` sessions and the Antigravity app first: their MindSlice MCP server keeps the
plugin folder open, and the install fails with "being used by another process".

Requirements: Python 3.12 or newer somewhere on the machine (`python3.12`/`python3.13` on `PATH`, Homebrew,
`~/.local/bin` or pyenv are found automatically), and a `python3` (or, on Windows, the `py` launcher) to start
it. Tested with the Antigravity CLI on Linux and Windows, and the Antigravity app on Windows; macOS should
behave like Linux, and is not verified yet.

The plugin does not bundle the MindSlice engine. In the first conversation it downloads the pinned release
from PyPI (`mindslice==0.2.7`, a 150 KB pure-Python wheel with no dependencies), checks its sha256 and unpacks
it into the plugin's data directory, where it stays across plugin updates. That first conversation needs
internet access (`HTTPS_PROXY` is honoured). Offline, install it yourself first:
`python3.12 -m pip install --user mindslice==0.2.7`, or download the wheel and set `MINDSLICE_PLUGIN_WHEEL`
to the file.

## What the plugin provides

| Part | What it does |
| --- | --- |
| MCP server `mindslice` | tools `manifest`, `search`, `read`, `write` on your workspace |
| `SessionStart` hook | injects MindSlice's usage instructions and your always-loaded cards at the start of every conversation, as numbered system messages, so nothing is truncated |
| `rules/AGENTS.md` | an always-on rule: call `manifest` when those pages are missing, and again after a compaction (Antigravity does not re-run the hook then) |
| `mindslice` command | the full MindSlice CLI on the agent's terminal PATH, pointed at your workspace |
| `/mindslice:setup` | choose and seed the workspace, migrate from a manual setup, verify |
| `/mindslice:review` | show staged memory changes and apply or discard the ones you approve |
| `/mindslice:slice-maintainer` | consolidate memory and bake reusable slices |

Setting changes restart the plugin's MCP server and apply from the next conversation on.

## Commands

With the agent's terminal tool, `mindslice` uses the plugin's workspace unless you pass `-w` or work inside
another MindSlice workspace:

```bash
mindslice plugin-status   # workspace, startup-memory usage, MCP self-check
mindslice status          # mounts, pending review, unbaked changes
mindslice diff            # staged changes
mindslice doctor          # full engine checks
```

With Antigravity's terminal sandbox on (`enableTerminalSandbox`), the agent's commands cannot read folders
outside the project, so a `mindslice` command that uses your workspace fails inside the sandbox and the agent
reruns it outside (tested on Windows). With the default permission preset that happens without a prompt; a
stricter preset asks you first, and where sandbox bypass is disabled the CLI steps of `/mindslice:review`,
`/mindslice:setup` and `/mindslice:slice-maintainer` do not work from the agent. The `SessionStart` hook and the
MCP tools are not sandboxed and always work.

In your own terminal, run the plugin's `bin/mindslice` (for example
`~/.gemini/config/plugins/mindslice/bin/mindslice`, or link it into `~/.local/bin`); on Windows,
`bin\mindslice.cmd`.

For nested sessions that must not see your personal memory (for example MindSlice-forge's `agy -p` runs),
set `MINDSLICE_PLUGIN_ISOLATE=1` in their environment.

## Uninstall

`agy plugin uninstall mindslice` (or `/plugin`, select mindslice, `ctrl+s`). Your workspace folder stays on
disk; delete it yourself if you no longer want it.

## License

Apache-2.0. The engine is the unmodified MindSlice release from PyPI; see `LICENSE` and `NOTICE`.
