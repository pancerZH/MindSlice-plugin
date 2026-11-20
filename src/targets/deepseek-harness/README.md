# MindSlice for DeepSeek Harness

Portable, human-readable long-term memory for DeepSeek Harness (Desktop, Web, and CLI), packaged from
[MindSlice](https://github.com/pancerZH/MindSlice): memory is plain Markdown cards in a folder you choose, your
standing memory (persona, reply language, standing rules) is delivered automatically in every session (and
refreshed after compaction), and changes to always-loaded memory wait for your approval.

## Install

1. **Clone or pull this repository** on the machine running DeepSeek Harness (e.g. `git pull` on Windows).
2. **Add the plugin in DeepSeek Harness Desktop**:
   - Open **Plugins → Add plugin**, and enter the local path to `plugins/deepseek-harness` inside your checkout
     (for example `C:\Users\<you>\MindSlice-plugin\plugins\deepseek-harness`), **or** install directly from GitHub
     with `https://github.com/pancerZH/MindSlice-plugin#main&path:plugins/deepseek-harness` (or via CLI:
     `dsh plugin --profile desktop add <path>`).
   - Enable **dsh-mindslice** (it ships plain Node.js ESM with zero npm dependencies and no build scripts).
3. **Choose the memory workspace**. DeepSeek Harness does not auto-generate a UI form for third-party plugin
   settings, so the plugin stores its settings in `settings.json` inside its data directory
   (`~/.dsh/profiles/desktop/plugin_data/mindslice/` on Desktop). Ask the agent to run `/mindslice-setup`, or
   configure it from your terminal:

   ```powershell
   # Windows (PowerShell)
   & "$env:USERPROFILE\.dsh\profiles\desktop\plugin_data\mindslice\bin\mindslice.cmd" plugin-config --workspace "$env:USERPROFILE\mindslice"
   ```

   ```bash
   # Linux / macOS
   ~/.dsh/profiles/desktop/plugin_data/mindslice/bin/mindslice plugin-config --workspace ~/mindslice
   ```

   (That stable launcher is written when the plugin first loads a session; before then, run
   `bin\mindslice.cmd` or `bin/mindslice` inside the installed `plugins/deepseek-harness` directory.)
   An existing MindSlice workspace (a folder with `mounts.toml`) is used as is; a new path or an empty folder
   is initialized at the next session start; a folder that already holds other files is refused, and nothing is
   written to it. Add `--stage-writes true` to send every write to staging for your approval (recommended for
   small local models).
4. Start a new session, then run `/mindslice-setup` to seed the workspace and verify delivery.

Optional `cordis.patch.yml` override: advanced users can also set `config.workspace` or `config.stageWrites` on
the `mindslice` row in `$DSH_HOME/profiles/desktop/cordis.patch.yml`.

Requirements: Python 3.12 or newer on the machine (`py` launcher or `python` on Windows; `python3.12`/`python3`
on POSIX).

The plugin does not bundle the MindSlice engine. On first use it downloads the pinned release from PyPI
(`mindslice==0.2.6`, a ~150 KB pure-Python wheel with no dependencies), checks its sha256, and unpacks it into
the plugin's data folder, where it stays across plugin updates. That first session needs internet access
(`HTTPS_PROXY` is honoured). Offline, install it yourself first (`python -m pip install --user mindslice==0.2.6`)
or set `MINDSLICE_PLUGIN_WHEEL` to the wheel file.

## What the plugin provides

| Part | What it does |
| --- | --- |
| MCP server `mindslice` | Tools `mcp__mindslice__manifest`, `mcp__mindslice__search`, `mcp__mindslice__read`, `mcp__mindslice__write` registered through `ctx.mcpManager` |
| Standing memory (`system-prompt/assemble`) | Delivers MindSlice's usage instructions and your always-loaded cards in the system prompt, cached per session and refreshed automatically after compaction |
| `mindslice` command | Full MindSlice CLI (`bin/mindslice` / `bin/mindslice.cmd` written to the plugin data dir, and exposed as `DSH_MINDSLICE_BIN` in agent shell calls) |
| `/mindslice-setup` | Choose and seed the workspace, migrate from a manual setup, and verify |
| `/mindslice-review` | Show staged memory changes and apply or discard the ones you approve |
| `/mindslice-slice-maintainer` | Consolidate memory and bake reusable slices |

Settings changes apply from the next new session (or after toggling the plugin off/on in **Plugins**).

## Commands

```bash
mindslice plugin-config   # the plugin's settings: workspace, stage_writes
mindslice plugin-status   # workspace, startup-memory usage, MCP self-check
mindslice status          # mounts, pending review, unbaked changes
mindslice diff            # staged changes
mindslice doctor          # full engine checks
```

On Windows PowerShell (`pwsh`) or bash, when DeepSeek Harness's sandbox restricts writes outside the project
directory, approve the wider-access prompt so `mindslice` commands can acquire the workspace lock or update
`settings.json`.

For nested sessions that must not see your personal memory, set `MINDSLICE_PLUGIN_ISOLATE=1` in their
environment.
