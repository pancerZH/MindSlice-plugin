---
name: setup
description: Set up the MindSlice memory plugin in Antigravity: choose or connect the memory workspace in the plugin's settings, seed it (an existing workspace, mounted slices or Markdown folders, or a short conversation), clean up an older manual MindSlice setup, and verify with `mindslice plugin-status`, `mindslice doctor` and a fresh `agy -p` conversation.
---

# MindSlice setup (plugin)

This plugin has already done what a manual MindSlice setup does by hand: it ships the `mindslice` engine and
command, registers the MindSlice MCP server (`mindslice`, tools `manifest`, `search`, `read`, `write`),
delivers the user's standing memory through its own `SessionStart` hook at the start of every conversation,
and adds an always-on rule (`rules/AGENTS.md`) that tells the agent to call `manifest` after a compaction.
**Do not install the `mindslice` package, register another MindSlice MCP server, add `boot` hooks or add a
"call manifest" rule to `GEMINI.md` or `AGENTS.md`**: that would load the memory twice. What is left is the
workspace: where it lives, how to seed it, and checking that a new conversation receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.

Placeholders used below:

- `<mindslice_bin>`: `mindslice`, which the plugin puts on the PATH of Antigravity's terminal tool (it is not on the user's own terminal `PATH`; `command -v mindslice` there prints its absolute path, inside the plugin folder). Without `-w` it uses the plugin's workspace, unless the current directory is inside another MindSlice workspace.
- `<workspace>`: the absolute path in the plugin's "Memory workspace" setting, which `mindslice plugin-status` prints.

**When something fails, go by the error report.** A failing `mindslice` command prints
`error [code]: message` on stderr, often with `Next:` steps; `mindslice doctor` prints a `Next:` line
under every failed check. Follow those, fix the cause and re-run, rather than working around the
failure or guessing at a configuration.

## Step 1 - Check the plugin

Run `mindslice plugin-status` with the terminal tool. It prints the configured workspace, the engine version,
how much of the startup capacity the standing memory uses, and the result of a handshake with the plugin's own
MCP entry point.

- **`mindslice: command not found`** (or a `mindslice` outside the plugin folder answers, without
  `plugin-status`): Antigravity appends the plugin's `bin/` at the end of `PATH`, so check `which -a mindslice`
  (`where mindslice` on Windows; or `~/.gemini/config/plugins/mindslice/bin/mindslice plugin-status`) first in case
  an older `mindslice` comes earlier on `PATH` (see "Migrating from a manual MindSlice setup"). If the plugin's own command is absent, the
  plugin is not enabled in this conversation: ask the user to open `/plugin` in the CLI, or give them
  `[mindslice](customization://mindslice)` in the Antigravity app (keyed on the install folder name if different),
  check that `mindslice` is installed and enabled, and start a new conversation. The plugin stays disabled until
  its settings are filled in (Step 3).
- **Python error** (`needs Python >= 3.12`, or `Python 3.12 or newer is required`): help the user install
  Python 3.12 or newer (Homebrew, the distribution's package, `uv python install 3.12`, or pyenv; on Windows
  the python.org installer). The plugin finds `python3.12`/`python3.13` on `PATH`, in `/opt/homebrew/bin`,
  `/usr/local/bin`, `~/.local/bin` and `~/.pyenv/shims`, and on Windows every interpreter the `py` launcher
  lists. Then start a new conversation.
- **"the MindSlice engine ... is not installed yet"**: the first conversation could not download the pinned
  engine from PyPI (offline, proxy, firewall). Show the user the reason; with their agreement, fix the network
  or proxy, or run the `pip install --user mindslice==<version>` command the message names, then start a new
  conversation.
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
   - Initialize the confirmed workspace only if needed: when the plugin's "Memory workspace" setting names a new or empty folder, the plugin initializes it by itself when its MCP server next starts (Step 3), so `<mindslice_bin> init <workspace>` is only needed to seed it before that, and only on a new or empty folder, never on a folder that already holds other files.
   - Mount each provided `.slice` or notes directory (`<mindslice_bin> -w <workspace> mount <directory>`).
     Plain Markdown and YAML-frontmatter notes are indexed read-only as is; Forge is not needed.
3. **Start from scratch in plain language**
   - Initialize the confirmed workspace only if needed: when the plugin's "Memory workspace" setting names a new or empty folder, the plugin initializes it by itself when its MCP server next starts (Step 3), so `<mindslice_bin> init <workspace>` is only needed to seed it before that, and only on a new or empty folder, never on a folder that already holds other files.
   - Ask 2-3 brief, concrete questions in plain language — no syntax required from the user:
     - How should the agent communicate with you? (reply language, tone, conciseness, standing rules)
     - What tools, languages, or conventions do you use by default? (e.g. `uv` vs `pip`, test commands, formatting)
     - What projects or ongoing topics are you working on right now?
   - Turn their answers into clean atomic cards:
     - **Standing reply rules (`load = "always"`)**: keep short; confirm the summary with the user and write directly via CLI with `--load always --no-stage` (e.g. `prefs/communication`) so it is active immediately without requiring a separate `mindslice apply`.
     - **Topic cards (`load = "as-needed"`)**: one focused sub-topic per card in `@overlay`, named by durable slot (`tooling/python`, `projects/overview`), never by a transient value (`tooling/uv`), with 3-8 search `aliases`.

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

Before them, run `<mindslice_bin> plugin-status`: it renders the startup pages the plugin's hook delivers,
reports their size against the startup capacity (a warning from 75% or when every page is in use, an error
when cards no longer fit) and checks the plugin's MCP entry point. Fix any error it prints.

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
- Explain how to reconnect and open a fresh session, how standing context loads at session start and after compaction (the plugin's `SessionStart` hook delivers it at the start of every conversation; after a compaction the plugin's always-on rule and the engine's instructions tell the model to call `manifest` again), which of the new-session checks you ran yourself with what result, and what remains unverified. Provide a standing-context check when applicable and a source-backed retrieval question for document imports. Reuse the builder's acceptance examples, with brief expected facts and links to source evidence; do not hand over questions whose answers the user has no way to check.
- Link the Forge report, ledgers and acceptance note for converted documents and the [review/bake workflow](https://github.com/pancerZH/MindSlice/blob/a3fc9a863db3c65432d2cdace2103211e595f74d/docs/workflow.md). Mention `review` when proposals are pending; avoid a full command tutorial or a list of every card/configuration path. Keep slice paths, dependencies, detailed results and setup configuration details in the ledger when one exists.

Aim for a short summary, a few actionable checks and links to details. Do not repeat the builder's
entire report when this setup skill calls it. Be clear that active overlay memory is already saved;
bake creates reusable versions, and future standing-card edits wait for approval. For later
disconnection or removal, use [`uninstall.md`](uninstall.md).

### Antigravity: the new-conversation checks

`agy -p` starts a one-shot conversation that loads the same plugins, rules, hooks and MCP servers as one the
user opens, so run the checks through it yourself (from the user's project directory). `agy` cannot forbid
single tools, so ask the model not to call any and check its answer names no tool call; a correct phrase can
then only come from the startup pages:

```bash
agy -p "Without calling any tool: what is the phrase in your MindSlice always-loaded memory? Answer NONE if you do not have one."
```

For the memory lookup, ask a question only a card can answer, without that restriction, and check the
answer used the MindSlice `search` or `read` tool. Plant and remove the temporary standing card with
`<mindslice_bin> write ... --load always --no-stage` and `--op delete` as `doctor` describes. For the
compaction check, the user runs `/compact` in a long conversation and asks for the phrase again: the model
should call `manifest` first, because Antigravity does not re-inject the pages after a compaction.

### Optional: `mindslice` in the user's own terminal

The plugin's command is on the PATH of Antigravity's terminal tool only. If the user wants it in their own
terminal (for example to run `mindslice review` themselves), offer to link it, after showing them the
command (`<plugin_bin>` is the plugin's `.../bin/mindslice` path printed by `command -v mindslice` or
`which -a mindslice`, typically `~/.gemini/config/plugins/mindslice/bin/mindslice`):

```bash
mkdir -p ~/.local/bin && ln -sf "<plugin_bin>" ~/.local/bin/mindslice
```

The link follows reinstalls into the same folder; uninstalling the plugin leaves it dangling. Skip it when
the user already has a `mindslice` installed from PyPI or a checkout. On Windows, cmd and PowerShell use
`<plugin>\bin\mindslice.cmd` directly.

## Migrating from a manual MindSlice setup

If MindSlice was set up by hand before (the `mindslice-setup` skill or the README), the old configuration
now delivers the memory a second time and exposes a second set of tools. Look for it, show the user what
you found, and remove it **only after they agree**, editing surgically so every other entry stays valid:

- **MCP server**: `~/.gemini/config/mcp_config.json`, and `.agents/mcp_config.json` in the projects the user
  names, for a server whose command runs `mindslice ... mcp` (the plugin's own server lives inside the plugin
  folder, not in these files). `agy mcp list` shows the configured servers and `agy mcp remove <name>` removes
  one. Note the `-w` path it used: if it differs from the plugin's workspace, ask which one the user wants to
  keep (Step 3).
- **Hooks**: `~/.gemini/config/hooks.json` and `.agents/hooks.json`, for a hook that runs `mindslice ... boot`.
- **Standing rule**: `~/.gemini/GEMINI.md`, `~/.gemini/config/` rules and project `GEMINI.md`/`AGENTS.md`
  files, for the paragraph that tells the agent to call the MindSlice server's `manifest` tool. The plugin's
  own rule (`rules/AGENTS.md`) replaces it.
- **The PyPI/checkout `mindslice` command** can stay, but it comes before the plugin's command on the
  terminal tool's PATH (the plugin's `bin/` is appended last) and does not know the plugin's workspace: if
  `command -v mindslice` does not print a path inside the plugin folder, find the plugin's own binary with
  `which -a mindslice` (`where mindslice` on Windows; typically `~/.gemini/config/plugins/mindslice/bin/mindslice`) and call that full path,
  or uninstall the other one with the user's agreement. Removing a `MINDSLICE_WORKSPACE` export from a shell
  profile is worth suggesting: it overrides the plugin's choice of workspace for every `mindslice` command.

Do not edit `~/.gemini/config/config.json` (it holds the plugin settings and permission grants; Antigravity
writes it itself). Then start a new conversation and run `mindslice plugin-status` and the Step 4 checks again.
