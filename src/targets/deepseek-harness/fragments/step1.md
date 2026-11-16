Run `<mindslice_bin> plugin-status` with the shell tool (`pwsh` on Windows, `bash` on POSIX). It prints the
configured workspace, the engine version, how much of the startup capacity the standing memory uses, and the
result of a handshake with the plugin's own MCP entry point.

- **No "MindSlice standing memory" pages and no `mcp__mindslice__*` tools**: check in DeepSeek Harness
  **Plugins** that `dsh-mindslice` is installed and enabled, then start a new session.
- **Python error** (`needs Python >= 3.12`, or `Python 3.12+ is required`): help the user install Python 3.12
  or newer (on Windows, the python.org installer with the `py` launcher; on macOS/Linux, Homebrew, distro
  package, `uv python install 3.12`, or pyenv). Then start a new session.
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
