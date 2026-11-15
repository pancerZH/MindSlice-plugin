Run `<mindslice_bin> plugin-status` with the shell tool (escalated: it reads the workspace and the plugin's
data folder). It prints the configured workspace, the engine version, how much of the startup capacity the
standing memory uses, and the result of a handshake with the plugin's own MCP entry point.

- **No "MindSlice standing memory" pages in this session** (no `[MindSlice standing memory · page 1/n]` text
  in your context, and no `[MindSlice plugin: ...]` notice): Codex skips plugin hooks until the user trusts
  them. Ask the user to run `/hooks` in Codex, review the MindSlice `SessionStart` hooks (they run
  `adapter/hook.py` from the plugin folder) and trust them; Codex asks again after every plugin update, because
  the trusted definition changed. Until then, use `<plugin root>/bin/mindslice` (see the placeholders above).
  If the MCP tools are missing too, the plugin is not installed or not enabled: ask the user to open
  `/plugins`, check that `mindslice` is installed and enabled, and start a new session.
- **Python error** (`needs Python >= 3.12`, or `Python 3.12 or newer is required`): help the user install
  Python 3.12 or newer (Homebrew, the distribution's package, `uv python install 3.12`, or pyenv; on Windows
  the python.org installer). The plugin finds `python3.12`/`python3.13` on `PATH`, in `/opt/homebrew/bin`,
  `/usr/local/bin`, `~/.local/bin` and `~/.pyenv/shims`, and on Windows every interpreter the `py` launcher
  lists. Then start a new session.
- **"the MindSlice engine ... is not installed yet"**: the first session could not download the pinned engine
  from PyPI (offline, proxy, firewall). Show the user the reason; with their agreement, fix the network or
  proxy, or run the `pip install --user mindslice==<version>` command the message names, then start a new
  session.
- **"no memory workspace configured"**: go on with Step 2 to agree on a location, then Step 3.
- **"not empty and is not a MindSlice workspace"**: the configured folder already holds other files. The
  plugin refuses to write into it. Agree on another location in Step 2.
- **A workspace is configured and the self-check passes**: tell the user which workspace is connected and
  ask whether they want to keep it (then seed it in Step 2, option 2 or 3, or skip to Step 4) or use another
  one.
