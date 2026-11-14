## Step 3 - Point the plugin at the workspace

The plugin's MCP server and hooks read the workspace from the plugin option **"Memory workspace"**
(`workspace`). Set it to the absolute `<workspace>` agreed in Step 2:

- **The user sets it** (always works): ask them to run `/plugin`, select **mindslice**, choose
  **Configure options**, and enter the path. Tell them the exact path to paste.
- **Or set it from the Bash tool**, if this Claude Code version has the command: show the user the command,
  then run it once they agree:
  `printf '%s' '{"workspace": "<workspace>"}' | claude plugin configure mindslice@mindslice --values-stdin`
  and check `claude plugin configure mindslice@mindslice` lists the new value.

Turn on **"Review every write"** (`stage_writes`) when the user runs a small local model, so every write
waits for their review.

**On Windows**, also set **"Python command"** (`python`) to `py`, or to the full path of a Python 3.12+
`python.exe`: Claude Code starts the MCP server with this command, and the default `python3` usually does not
exist on Windows (or is the Microsoft Store placeholder). With the command above, pass both values:
`{"workspace": "<workspace>", "python": "py"}`. Keep the default on Linux and macOS.

What the plugin does with the folder at the next session start:

| Folder | Result |
| --- | --- |
| has `mounts.toml` (an existing workspace) | used as is |
| does not exist yet, or is empty | initialized as a new workspace |
| holds other files but no `mounts.toml` | refused: nothing is written, the session reports it |

Option changes take effect in a **new session**: the current one keeps the MCP server and hooks it started
with. Ask the user to start one (or use `claude -p` for the checks in Step 4) before validating.
