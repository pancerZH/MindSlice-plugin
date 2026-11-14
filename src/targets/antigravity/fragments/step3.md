## Step 3 - Point the plugin at the workspace

The plugin's MCP server reads the workspace from the plugin setting **"Memory workspace"** (`workspace`); its
startup hook follows the MCP server. Antigravity asks for the settings when the plugin is turned on, and the
plugin stays disabled until they are filled in. The user changes them (you cannot: Antigravity keeps them in
its own configuration, which you must not edit):

- **Antigravity CLI**: run `/plugin`, select **mindslice**, choose **Configure MCP servers...**, and enter the
  absolute `<workspace>` agreed in Step 2. Tell them the exact path to paste.
- **Antigravity app / IDE**: open `[mindslice](customization://mindslice)` (keyed on the plugin's install folder
  name if different) on the Customizations page and fill in the same field.

**"Review every write"** (`stage_writes`) is required too: `false` for most users, `true` when the user runs a
small local model, so every write waits for their review.

What the plugin does with the folder when its MCP server starts:

| Folder | Result |
| --- | --- |
| has `mounts.toml` (an existing workspace) | used as is |
| does not exist yet, or is empty | initialized as a new workspace |
| holds other files but no `mounts.toml` | refused: nothing is written, the MCP server does not start and the next conversation reports it |

Saving the settings restarts the plugin's MCP server; the new workspace reaches the startup pages from the
**next conversation** on. Ask the user to start one (or use `agy -p` for the checks in Step 4) before
validating. The CLI and the Antigravity app keep separate plugin data, so each one picks up the setting when
its own MCP server starts.
