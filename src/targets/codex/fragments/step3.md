## Step 3 - Point the plugin at the workspace

Codex has no plugin options, so the plugin keeps its settings in `settings.json` in its data folder
(`~/.codex/plugins/data/mindslice-mindslice/`); its MCP server and hook read them at every session start.
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

Settings take effect in a **new session**: the current one keeps the MCP server and pages it started with.
Ask the user to start one (or use `codex exec` for the checks in Step 4) before validating.

By default Codex asks before each `write` call of the MindSlice tools (`manifest`, `search` and `read` are
read-only and run without asking). If the user wants memory writes to go through without a prompt, they can
choose to always allow it when Codex asks.

Every `mindslice` command that uses the workspace takes a lock file in it, so Codex asks the user to approve
each one. If the user wants to avoid those prompts, suggest making the workspace a writable root of
Codex's sandbox: `codex --add-dir "<workspace>"`, or `writable_roots = ["<workspace>"]` under
`[sandbox_workspace_write]` in `~/.codex/config.toml` (only with their agreement; `plugin-config` still needs
the escalation).
