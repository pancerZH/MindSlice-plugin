---
name: mindslice-setup
description: Set up the MindSlice memory plugin in DeepSeek Harness: choose or connect the memory workspace with `mindslice plugin-config`, seed it (an existing workspace, mounted slices or Markdown folders, or a short conversation), clean up an older manual MindSlice setup, and verify with `mindslice plugin-status`, `mindslice doctor` and a fresh session.
---

# MindSlice setup (plugin)

This plugin has already done what a manual MindSlice setup does by hand: it provisions the `mindslice`
engine and command, registers the `mindslice` MCP server (`mcp__mindslice__manifest`, `search`, `read`,
`write`) via `ctx.mcpManager`, and delivers your standing memory in the system prompt at session start and
after compaction. **Do not add another MindSlice MCP server, add `boot` hooks, or add a "call manifest"
rule to `AGENTS.md`**: that would load the memory twice. What is left is choosing the workspace (where it
lives, how to seed it), and checking that a new session receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.

Placeholders used below:

- `<mindslice_bin>`: the plugin's `mindslice` command, by the absolute path the standing memory pages give (or `$env:DSH_MINDSLICE_BIN` in PowerShell / `"$DSH_MINDSLICE_BIN"` in bash; typically `$DSH_HOME/profiles/desktop/plugin_data/mindslice/bin/mindslice.cmd` on Windows or `mindslice` on POSIX). Before the plugin has loaded a session once, use `<plugin root>/bin/mindslice.cmd` (Windows) or `<plugin root>/bin/mindslice` (POSIX), where `<plugin root>` is the folder two levels above this skill's directory (it holds `package.json`). Without `-w` it uses the plugin's workspace, unless the current directory is inside another MindSlice workspace.
- `<workspace>`: the absolute path in the plugin's settings (`<mindslice_bin> plugin-config` shows it; `mindslice plugin-status` prints it too).

**When something fails, go by the error report.** A failing `mindslice` command prints
`error [code]: message` on stderr, often with `Next:` steps; `mindslice doctor` prints a `Next:` line
under every failed check. Follow those, fix the cause and re-run, rather than working around the
failure or guessing at a configuration.

## Step 1 - Check the plugin

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

## Step 2 - Confirm location and how to seed the workspace

**Do not create `~/mindslice` silently before asking.** Unless the user already specified them, ask once (in their language) to confirm two things together — offering sensible defaults so they can simply accept defaults or customize:

- **Workspace directory (`<workspace>`)**: where the memory folder should live on disk (suggest `~/mindslice` by default, or their chosen path such as `~/memories/work` or `~/worlds/doskvol`). Resolve it to an absolute path.
- **How to start**:

1. **Connect an existing MindSlice workspace**
   - If the supplied path has `mounts.toml`, use it directly as `<workspace>` and continue to Step 3.
     Do not reinitialize it or mount its root directory as a slice.
2. **Mount existing slices or Markdown folders**
   - Initialize the confirmed workspace only if needed: when the plugin's workspace setting (`plugin-config --workspace`) names a new or empty folder, the plugin initializes it by itself at the next session start (Step 3), so `<mindslice_bin> init <workspace>` is only needed to seed it before that, and only on a new or empty folder, never on a folder that already holds other files.
   - Mount each provided `.slice` or notes directory (`<mindslice_bin> -w <workspace> mount <directory>`).
     Plain Markdown and YAML-frontmatter notes are indexed read-only as is; Forge is not needed.
3. **Start from scratch in plain language**
   - Initialize the confirmed workspace only if needed: when the plugin's workspace setting (`plugin-config --workspace`) names a new or empty folder, the plugin initializes it by itself at the next session start (Step 3), so `<mindslice_bin> init <workspace>` is only needed to seed it before that, and only on a new or empty folder, never on a folder that already holds other files.
   - Ask 2-3 brief, concrete questions in plain language — no syntax required from the user:
     - How should the agent communicate with you? (reply language, tone, conciseness, standing rules)
     - What tools, languages, or conventions do you use by default? (e.g. `uv` vs `pip`, test commands, formatting)
     - What projects or ongoing topics are you working on right now?
   - Turn their answers into clean atomic cards:
     - **Standing reply rules (`load = "always"`)**: keep short; confirm the summary with the user and write directly via CLI with `--load always --no-stage` (e.g. `prefs/communication`) so it is active immediately without requiring a separate `mindslice apply`.
     - **Topic cards (`load = "as-needed"`)**: one focused sub-topic per card in `@overlay`, named by durable slot (`tooling/python`, `projects/overview`), never by a transient value (`tooling/uv`), with 3-8 search `aliases`.

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

## Step 4 - Validate and hand off

Run `<mindslice_bin> -w <workspace> doctor`. It checks the runtime, workspace, mounts, cards, index,
startup payload and a real MCP handshake; exit code 1 means a check failed, and each failure prints
a `Next:` line. Fix every failure and explain remaining warnings.

`doctor` cannot see your harness. Two of its lines are about it, and both are settled only by a new
session:

- **`client_connection`** names the app that last started this workspace's MCP server and the tools
  it called; the server records this itself. `[PENDING]` means no app has. After the harness has
  reloaded its configuration and opened a session, it must name your harness. If it does not, the
  registration is not being loaded, whatever the configuration file says.
- **`[MANUAL] client_session`** lists the checks: the server and its four tools, the **startup
  check** (a temporary standing card holding a phrase the model cannot guess, asked for in a new
  session, then removed), a real memory lookup, and the standing memory after a compaction.

Before them, run `<mindslice_bin> plugin-status`: it renders the startup pages the plugin delivers into
the system prompt, reports their size against the startup capacity (a warning from 75% or when every page is
in use, an error when cards no longer fit), and checks the plugin's MCP entry point. Fix any error it prints.

**Start the new session yourself when the harness can.** Most command-line harnesses have a
one-shot, non-interactive mode that takes a prompt and prints the reply (see the harness's `--help`).
A session started that way loads the same MCP configuration, rules and hooks as one the user opens,
so it is a real test, and you can read its answer and its tool calls. Run the startup check through
it exactly as `doctor` prints it: plant the phrase, ask in the new session, read the result, remove
the card.

- The phrase comes back: standing memory reaches the model. Then ask the memory-lookup question the
  same way.
- `NONE`, or the model had to `search` or `read` for it: delivery failed. Fix Step 3 and ask again
  in another new session. Do not report setup as done on a configuration you have not seen work.

Where the harness has no way to start a session from here, say that setup is **pending acceptance**
and hand the user those same steps with the exact commands and prompt, instead of claiming it passed.
A compaction can rarely be triggered from outside a conversation: hand that check over unless the
harness has a command for it.

Then run `<mindslice_bin> -w <workspace> status` for the mounts, card counts and pending review you
report, and give a compact handoff in the user's language:

- State what is ready: workspace path, connected app/server name, slice/card counts and standing-card count. Distinguish built artifacts from successfully mounted slices.
- Summarize checks and any material gaps or pending proposals. Separate local engine checks, source/retrieval spot checks and actual client-session verification; passing one does not prove the others.
- Explain how to reconnect and open a fresh session, how standing context loads at session start and after compaction (the plugin injects it into the system prompt at session start and refreshes it after compaction; the MCP server's instructions tell the model to call `manifest` if the pages are missing), which of the new-session checks you ran yourself with what result, and what remains unverified. Provide a standing-context check when applicable and a source-backed retrieval question for document imports. Reuse the builder's acceptance examples, with brief expected facts and links to source evidence; do not hand over questions whose answers the user has no way to check.
- Link the Forge report, ledgers and acceptance note for converted documents and the [review/bake workflow](https://github.com/pancerZH/MindSlice/blob/f220705059d8721d4042c452b88daa20822318b0/docs/workflow.md). Mention `review` when proposals are pending; avoid a full command tutorial or a list of every card/configuration path. Keep slice paths, dependencies, detailed results and setup configuration details in the ledger when one exists.

Aim for a short summary, a few actionable checks and links to details. Do not repeat the builder's
entire report when this setup skill calls it. Be clear that active overlay memory is already saved;
bake creates reusable versions, and future standing-card edits wait for approval. For later
disconnection or removal, use [`uninstall.md`](uninstall.md).

### DeepSeek Harness: the new-session checks

Ask the user to start a **new session** (after disabling/re-enabling `dsh-mindslice` in **Plugins** if
`workspace` was just changed for the first time so the MCP server restarts with the workspace) and verify:

1. **Standing memory without tool calls**: ask the model "Without calling any tool, what is the phrase in your
   MindSlice always-loaded memory?" — a correct phrase confirms the system-prompt delivery arrived.
2. **Memory lookup**: ask a question only a `load="as-needed"` card answers, and verify the model calls
   `mcp__mindslice__search` or `mcp__mindslice__read`.
3. **Compaction**: run `/compact` in a session and ask for the standing-memory phrase again to confirm the
   system prompt keeps and refreshes the standing memory after compaction.

## Migrating from a manual MindSlice setup

If MindSlice was set up by hand before, the old configuration now delivers the memory a second time or
exposes a second set of MCP tools. Look for it, show the user what you found, and remove it **only after they
agree**, editing surgically so every other entry stays valid:

- **Manual MCP server**: check `$DSH_HOME/cordis.patch.yml` and `$DSH_HOME/profiles/<profile>/cordis.patch.yml`
  (and DeepSeek Harness MCP settings) for a `dsh-mcp-client` or `mcp-manager` `mindslice` entry other than
  this plugin (`dsh-mindslice`). Note any `-w` path it used: if it differs from the plugin's workspace, ask
  which one the user wants to keep (Step 3).
- **Manual prompt / hooks**: check `$DSH_HOME/cordis.patch.yml`, `$DSH_HOME/profiles/<profile>/cordis.patch.yml`,
  or `hooks-claude-code` / `hooks-codex` configs for a rule or hook running `mindslice ... boot`.
- **Standing rule**: check `~/.dsh/AGENTS.md` (or project `AGENTS.md` / `CLAUDE.md`) for a paragraph telling
  the agent to call the MindSlice server's `manifest` tool. The plugin's standing memory pages and MCP server
  instructions replace it.
- **Manual skills**: check `~/.dsh/skills/` or `~/.agents/skills/` for older `mindslice-*` copies if the user
  no longer wants them overriding the bundled skills.
- **The PyPI/checkout `mindslice` command** itself can stay; the plugin does not use it. Removing a
  `MINDSLICE_WORKSPACE` environment variable is worth suggesting: it overrides the plugin's choice of
  workspace for every `mindslice` command.

Then start a new session and run `mindslice plugin-status` and the Step 4 checks again.
