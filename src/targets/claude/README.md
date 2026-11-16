# MindSlice for Claude Code

Portable, human-readable long-term memory for Claude Code, packaged from
[MindSlice](https://github.com/pancerZH/MindSlice): memory is plain Markdown cards in a folder you choose,
the user's standing memory (persona, reply language, standing rules) reaches every session, and changes to
it wait for your approval.

## Install

```text
/plugin marketplace add pancerZH/MindSlice-plugin
/plugin install mindslice@mindslice
```

When asked for **Memory workspace**, enter a folder:

- an existing MindSlice workspace (a folder with `mounts.toml`) is used as is;
- a new path or an empty folder is initialized as a new workspace;
- a folder that already holds other files is refused, and nothing is written to it.

Start a new session, then run `/mindslice:setup` to seed the memory and verify that it reaches the model.

Requirements: Python 3.12 or newer somewhere on the machine (`python3.12`/`python3.13` on `PATH`, Homebrew,
`~/.local/bin` or pyenv are found automatically). Supported on Linux, macOS and WSL.

**Windows** (native): install [Git for Windows](https://git-scm.com/downloads/win)
(Claude Code runs the plugin's hooks and the `mindslice` command in Git Bash) and Python 3.12+ from
python.org (the plugin starts it with the `py` launcher). Without Git Bash, Claude Code falls back to
PowerShell, which this plugin does not support yet.

The plugin does not bundle the MindSlice engine. In the first session it downloads the pinned release from
PyPI (`mindslice==0.1.8`, a 150 KB pure-Python wheel with no dependencies), checks its sha256 and unpacks it
into the plugin's data directory, where it stays across plugin updates. That first session needs internet
access (`HTTPS_PROXY` is honoured). Offline, install it yourself first:
`python3.12 -m pip install --user mindslice==0.1.8`, or download the wheel and set `MINDSLICE_PLUGIN_WHEEL`
to the file.

## What the plugin provides

| Part | What it does |
| --- | --- |
| MCP server `mindslice` | tools `manifest`, `search`, `read`, `write` on your workspace |
| `SessionStart` hooks | deliver MindSlice's usage instructions and your always-loaded cards at every start, resume, `/clear` and `/compact`, split into pages so nothing is truncated |
| `mindslice` command | the full MindSlice CLI inside Claude's Bash tool, pointed at your workspace |
| `/mindslice:setup` | choose and seed the workspace, migrate from a manual setup, verify |
| `/mindslice:review` | show staged memory changes and apply or discard the ones you approve |
| `/mindslice:slice-maintainer` | consolidate memory and bake reusable slices |

Options (`/plugin` → mindslice → Configure options): **Memory workspace**; **Review every write** (stage
every agent write for your approval; recommended for small local models). Option changes apply to new
sessions.

## Commands

In Claude's Bash tool, `mindslice` uses the plugin's workspace unless you pass `-w` or work inside another
MindSlice workspace:

```bash
mindslice plugin-status   # workspace, startup-memory usage, MCP self-check
mindslice status          # mounts, pending review, unbaked changes
mindslice diff            # staged changes
mindslice doctor          # full engine checks
```

At session start the plugin writes a small `mindslice` launcher to its data directory and puts it on the Bash
tool's `PATH`. To use it in your own terminal, link it: `ln -sf "$(command -v mindslice)" ~/.local/bin/mindslice`
(run in the Bash tool; the launcher keeps its path across plugin updates). On Windows, cmd and PowerShell use the
`mindslice.cmd` beside it (`cygpath -w "$(command -v mindslice).cmd"` in the Bash tool prints its path).

For nested sessions that must not see your personal memory (for example MindSlice-forge's `claude -p`
runs), set `MINDSLICE_PLUGIN_ISOLATE=1` in their environment.

## Uninstall

`/plugin uninstall mindslice@mindslice`. Your workspace folder stays on disk; delete it yourself if you no
longer want it.

## License

Apache-2.0. The engine is the unmodified MindSlice release from PyPI; see `LICENSE` and `NOTICE`.
