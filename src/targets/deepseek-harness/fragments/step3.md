## Step 3 - Point the plugin at the workspace

DeepSeek Harness Desktop has no auto-generated form for third-party plugin settings, so the plugin stores its
settings in `settings.json` inside its data directory (`$DSH_HOME/profiles/<profile>/plugin_data/mindslice/`).
Show the user the command, then run it once they agree:

```bash
<mindslice_bin> plugin-config --workspace "<workspace>"
```

It refuses a relative path, a folder inside the plugin's own folders, and a folder that holds other files but
no `mounts.toml`, and changes nothing then. Add `--stage-writes true` when the user runs a small local model,
so every write waits for their review (`--stage-writes false` turns it off again). `<mindslice_bin>
plugin-config` without options shows the current settings; `--unset-workspace` disconnects the workspace.

What the plugin does with the folder at the next session start:

| Folder | Result |
| --- | --- |
| has `mounts.toml` (an existing workspace) | used as is |
| does not exist yet, or is empty | initialized as a new workspace |
| holds other files but no `mounts.toml` | refused: nothing is written, the session reports it |

Settings take effect in a **new session** (or after toggling the plugin off and back on in **Plugins** so the
MCP server restarts): ask the user to start a new session before validating in Step 4.

If DeepSeek Harness's sandbox restricts shell commands from writing outside the project directory, approve
the permission prompt when running `mindslice` commands that touch the workspace or `settings.json`.
