Run `mindslice plugin-status` with the terminal tool. It prints the configured workspace, the engine version,
how much of the startup capacity the standing memory uses, and the result of a handshake with the plugin's own
MCP entry point.

- **`mindslice: command not found`** (or a `mindslice` outside the plugin folder answers, without
  `plugin-status`): Antigravity appends the plugin's `bin/` at the end of `PATH`, so check `which -a mindslice`
  (`where mindslice` on Windows; or `~/.gemini/config/plugins/mindslice/bin/mindslice plugin-status`) first in case
  an older `mindslice` comes earlier on `PATH` (see "Migrating from a manual MindSlice setup"). If the plugin's own command is absent, the
  plugin is not enabled in this conversation: ask the user to open `/plugin` in the CLI, or give them
  `[mindslice](customization://mindslice)` in the Antigravity app (keyed on the install folder name if different),
  check that `mindslice` is installed and enabled, and start a new conversation. The plugin stays disabled until
  its settings are filled in (Step 3).
- **Python error** (`needs Python >= 3.12`, or `Python 3.12 or newer is required`): help the user install
  Python 3.12 or newer (Homebrew, the distribution's package, `uv python install 3.12`, or pyenv; on Windows
  the python.org installer). The plugin finds `python3.12`/`python3.13` on `PATH`, in `/opt/homebrew/bin`,
  `/usr/local/bin`, `~/.local/bin` and `~/.pyenv/shims`, and on Windows every interpreter the `py` launcher
  lists. Then start a new conversation.
- **"the MindSlice engine ... is not installed yet"**: the first conversation could not download the pinned
  engine from PyPI (offline, proxy, firewall). Show the user the reason; with their agreement, fix the network
  or proxy, or run the `pip install --user mindslice==<version>` command the message names, then start a new
  conversation.
- **"no memory workspace configured"**: go on with Step 2 to agree on a location, then Step 3.
- **"not empty and is not a MindSlice workspace"**: the configured folder already holds other files. The
  plugin refuses to write into it. Agree on another location in Step 2.
- **A workspace is configured and the self-check passes**: tell the user which workspace is connected and
  ask whether they want to keep it (then seed it in Step 2, option 2 or 3, or skip to Step 4) or use another
  one.
