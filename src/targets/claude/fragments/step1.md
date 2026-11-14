Run `mindslice plugin-status` in the Bash tool. It prints the configured workspace, the engine version, how
much of the startup capacity the standing memory uses, and the result of a handshake with the plugin's own
MCP entry point.

- **`mindslice: command not found`**: the plugin's session-start hook did not run in this session (the plugin
  is disabled, or the session started before it was installed or before Python 3.12+ was available). Ask the
  user to run `/plugin`, check that `mindslice` is installed and enabled, and start a new session.
- **Python error** (`needs Python >= 3.12`, or `no Python found`): help the user install Python 3.12 or newer
  (Homebrew, the distribution's package, `uv python install 3.12`, or pyenv; on Windows the python.org
  installer). The plugin finds `python3.12`/`python3.13` on `PATH`, in `/opt/homebrew/bin`, `/usr/local/bin`,
  `~/.local/bin` and `~/.pyenv/shims`, and on Windows every interpreter the `py` launcher lists. Then start a
  new session.
- **Windows: the `mcp__plugin_mindslice_mindslice__*` tools are missing** although the startup pages arrived:
  the MCP server starts with the plugin option "Python command" (default `python3`, which usually does not
  run on Windows). Have the user set it to `py` (Step 3) and start a new session. Windows needs Git for
  Windows: without Git Bash, Claude Code runs hooks in PowerShell, which the plugin does not support yet.
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
