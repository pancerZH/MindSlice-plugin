# MindSlice for Codex

Portable, human-readable long-term memory for the Codex CLI, packaged from
[MindSlice](https://github.com/pancerZH/MindSlice): memory is plain Markdown cards in a folder you choose, the
user's standing memory (persona, reply language, standing rules) reaches every session, and changes to it wait
for your approval.

## Install

```bash
codex plugin marketplace add pancerZH/MindSlice-plugin
codex plugin add mindslice@mindslice
```

(or `/plugins` in Codex, marketplace **MindSlice**). Then, in Codex:

1. **Trust the startup hook.** Codex skips a plugin's hooks until you review them: run `/hooks` and trust the
   MindSlice `SessionStart` hook (it runs `adapter/hook.py` from the plugin folder). Codex asks again after
   each plugin update. Without it the MCP tools still work, but your standing memory is not delivered at
   session start.
2. **Choose the memory workspace.** Codex has no plugin options, so the plugin keeps its settings in its data
   folder. Ask Codex for `$mindslice:setup`, or set it yourself:

   ```bash
   ~/.codex/plugins/data/mindslice-mindslice/bin/mindslice plugin-config --workspace ~/mindslice
   ```

   (that launcher exists once the hook has run; before, use `bin/mindslice` in the plugin folder,
   `~/.codex/plugins/cache/mindslice/mindslice/<version>/`). An existing MindSlice workspace (a folder with
   `mounts.toml`) is used as is; a new path or an empty folder is initialized at the next session start; a
   folder that already holds other files is refused, and nothing is written to it. Add `--stage-writes true` to
   send every change the agent makes to staging for your approval (recommended for small local models).
3. Start a new session, then run `$mindslice:setup` to seed the memory and verify that it reaches the model.

To update: `codex plugin marketplace upgrade mindslice`, then `codex plugin add mindslice@mindslice` again
(your settings stay in the data folder), and trust the updated hook in `/hooks`.

Requirements: Python 3.12 or newer somewhere on the machine (`python3.12`/`python3.13` on `PATH`, Homebrew,
`~/.local/bin` or pyenv are found automatically), and a `python3` to start it. Tested with Codex CLI 0.169.0 on
Linux; macOS should behave the same, and is not verified yet. Windows is not verified.

The plugin does not bundle the MindSlice engine. In the first session it downloads the pinned release from PyPI
(`mindslice==0.2.3`, a 150 KB pure-Python wheel with no dependencies), checks its sha256 and unpacks it into
the plugin's data folder, where it stays across plugin updates. That first session needs internet access
(`HTTPS_PROXY` is honoured). Offline, install it yourself first: `python3.12 -m pip install --user
mindslice==0.2.3`, or download the wheel and set `MINDSLICE_PLUGIN_WHEEL` to the file.

## What the plugin provides

| Part | What it does |
| --- | --- |
| MCP server `mindslice` | tools `manifest`, `search`, `read`, `write` on your workspace; the first three are read-only and run without an approval prompt |
| `SessionStart` hook | delivers MindSlice's usage instructions and your always-loaded cards at every session start, resume, clear, fork and compaction, as numbered pages, so nothing is truncated |
| `mindslice` command | the full MindSlice CLI, pointed at your workspace; the startup pages give the agent its path |
| `$mindslice:setup` | choose and seed the workspace, migrate from a manual setup, verify |
| `$mindslice:review` | show staged memory changes and apply or discard the ones you approve |
| `$mindslice:slice-maintainer` | consolidate memory and bake reusable slices |

Settings changes apply from the next session on.

Codex asks before each `write` call. To let memory writes through without a prompt, choose to always allow it
when Codex asks, or add to `~/.codex/config.toml`:

```toml
[plugins."mindslice@mindslice".mcp_servers.mindslice.tools.write]
approval_mode = "approve"
```

## Commands

The plugin's command is not on any `PATH`. At session start it writes a launcher whose path stays the same
across plugin updates, `~/.codex/plugins/data/mindslice-mindslice/bin/mindslice` (under `$CODEX_HOME` if you
set it). Without `-w` it uses the plugin's workspace, unless you work inside another MindSlice workspace:

```bash
mindslice plugin-config   # the plugin's settings: workspace, stage_writes
mindslice plugin-status   # workspace, startup-memory usage, MCP self-check
mindslice status          # mounts, pending review, unbaked changes
mindslice diff            # staged changes
mindslice doctor          # full engine checks
```

Link it into your own terminal with `ln -sf ~/.codex/plugins/data/mindslice-mindslice/bin/mindslice
~/.local/bin/mindslice`.

Codex's sandbox keeps the agent's shell commands from writing outside the project, and every `mindslice`
command that uses the workspace takes a lock file in it, so the agent runs them with escalated permissions,
which Codex asks you to approve (with `-a never` they cannot run). To avoid the prompts, make the workspace a
writable root, for example `codex --add-dir ~/mindslice`, or in `~/.codex/config.toml`:

```toml
[sandbox_workspace_write]
writable_roots = ["/home/you/mindslice"]
```

`plugin-config` writes the plugin's data folder and always needs the escalation. The hook and the MCP server
are not sandboxed and always work.

For nested sessions that must not see your personal memory (for example MindSlice-forge's `codex exec` runs),
set `MINDSLICE_PLUGIN_ISOLATE=1` in their environment.

## Uninstall

`codex plugin remove mindslice@mindslice` (and `codex plugin marketplace remove mindslice`). Your workspace
folder stays on disk, and so does the plugin's data folder (`~/.codex/plugins/data/mindslice-mindslice/`, with
the engine copy and your settings); delete them yourself if you no longer want them.

## License

Apache-2.0. The engine is the unmodified MindSlice release from PyPI; see `LICENSE` and `NOTICE`.
