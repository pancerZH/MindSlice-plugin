---
name: setup
description: Set up the MindSlice memory plugin in Claude Code: choose or connect the memory workspace in the plugin's options, seed it (an existing workspace, mounted slices or Markdown folders, or a short conversation), clean up an older manual MindSlice setup, and verify with `mindslice plugin-status`, `mindslice doctor` and a fresh `claude -p` session.
---

# MindSlice setup (plugin)

This plugin has already done what a manual MindSlice setup does by hand: it ships the `mindslice` engine and
command, registers the MindSlice MCP server (tools `mcp__plugin_mindslice_mindslice__manifest`, `search`,
`read`, `write`), and delivers the user's standing memory through its own `SessionStart` hooks at every
session start, resume, clear and compaction. **Do not install the `mindslice` package, register another
MindSlice MCP server, add `boot` hooks or add a "call manifest" rule to `CLAUDE.md`**: that would load the
memory twice. What is left is the workspace: where it lives, how to seed it, and checking that a new session
receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.

Placeholders used below:

- `<mindslice_bin>`: `mindslice`, which the plugin puts on the Bash tool's `PATH` (it is not on the user's own terminal `PATH`; `command -v mindslice` in the Bash tool prints its absolute path). Without `-w` it uses the plugin's workspace, unless the current directory is inside another MindSlice workspace.
- `<workspace>`: the absolute path in the plugin's "Memory workspace" option, which `mindslice plugin-status` prints.

**When something fails, go by the error report.** A failing `mindslice` command prints
`error [code]: message` on stderr, often with `Next:` steps; `mindslice doctor` prints a `Next:` line
under every failed check. Follow those, fix the cause and re-run, rather than working around the
failure or guessing at a configuration.

## Step 1 - Check the plugin

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
- **Windows: the startup pages are missing**: Windows needs Git for Windows; without Git Bash, Claude Code
  runs hooks in PowerShell, which the plugin does not support yet.
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
   - Initialize the confirmed workspace only if needed: when the plugin's "Memory workspace" option names a new or empty folder, the plugin initializes it by itself at the next session start (Step 3), so `<mindslice_bin> init <workspace>` is only needed to seed it before that, and only on a new or empty folder, never on a folder that already holds other files.
   - Mount each provided `.slice` or notes directory (`<mindslice_bin> -w <workspace> mount <directory>`).
     Plain Markdown and YAML-frontmatter notes are indexed read-only as is; Forge is not needed.
3. **Start from scratch in plain language**
   - Initialize the confirmed workspace only if needed: when the plugin's "Memory workspace" option names a new or empty folder, the plugin initializes it by itself at the next session start (Step 3), so `<mindslice_bin> init <workspace>` is only needed to seed it before that, and only on a new or empty folder, never on a folder that already holds other files.
   - Ask 2-3 brief, concrete questions in plain language — no syntax required from the user:
     - How should the agent communicate with you? (reply language, tone, conciseness, standing rules)
     - What tools, languages, or conventions do you use by default? (e.g. `uv` vs `pip`, test commands, formatting)
     - What projects or ongoing topics are you working on right now?
   - Turn their answers into clean atomic cards:
     - **Standing reply rules (`load = "always"`)**: keep short; confirm the summary with the user and write directly via CLI with `--load always --no-stage` (e.g. `prefs/communication`) so it is active immediately without requiring a separate `mindslice apply`.
     - **Topic cards (`load = "as-needed"`)**: one focused sub-topic per card in `@overlay`, named by durable slot (`tooling/python`, `projects/overview`), never by a transient value (`tooling/uv`), with 3-8 search `aliases`.

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

What the plugin does with the folder at the next session start:

| Folder | Result |
| --- | --- |
| has `mounts.toml` (an existing workspace) | used as is |
| does not exist yet, or is empty | initialized as a new workspace |
| holds other files but no `mounts.toml` | refused: nothing is written, the session reports it |

Option changes take effect in a **new session**: the current one keeps the MCP server and hooks it started
with. Ask the user to start one (or use `claude -p` for the checks in Step 4) before validating.

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

Before them, run `<mindslice_bin> plugin-status`: it renders the startup pages the plugin's hooks deliver,
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
- Explain how to reconnect and open a fresh session, how standing context loads at session start and after compaction (the plugin's `SessionStart` hooks deliver it on every start, resume, `/clear` and `/compact`; the MCP server's instructions tell the model to call `manifest` if the pages are missing), which of the new-session checks you ran yourself with what result, and what remains unverified. Provide a standing-context check when applicable and a source-backed retrieval question for document imports. Reuse the builder's acceptance examples, with brief expected facts and links to source evidence; do not hand over questions whose answers the user has no way to check.
- Link the Forge report, ledgers and acceptance note for converted documents and the [review/bake workflow](https://github.com/pancerZH/MindSlice/blob/e2b85ad0df537fa862ec555f3ba5c43c59554b44/docs/workflow.md). Mention `review` when proposals are pending; avoid a full command tutorial or a list of every card/configuration path. Keep slice paths, dependencies, detailed results and setup configuration details in the ledger when one exists.

Aim for a short summary, a few actionable checks and links to details. Do not repeat the builder's
entire report when this setup skill calls it. Be clear that active overlay memory is already saved;
bake creates reusable versions, and future standing-card edits wait for approval. For later
disconnection or removal, use [`uninstall.md`](uninstall.md).

### Claude Code: the new-session checks

`claude -p` starts a one-shot session that loads the same plugins, hooks and MCP servers as one the user
opens, so run the checks through it yourself. For the startup check, forbid the memory tools, so a correct
answer can only come from the startup pages:

```bash
claude -p "Without calling any tool: what is the phrase in your MindSlice always-loaded memory? Answer NONE if you do not have one." \
  --disallowedTools "mcp__plugin_mindslice_mindslice__manifest,mcp__plugin_mindslice_mindslice__search,mcp__plugin_mindslice_mindslice__read"
```

For the memory lookup, ask a question only a card can answer, without that restriction, and check the
answer used `mcp__plugin_mindslice_mindslice__search` or `read`. Plant and remove the temporary
standing card with `<mindslice_bin> write ... --load always --no-stage` and `--op delete` as `doctor`
describes. A compaction cannot be triggered from `claude -p`: hand the user that check (run `/compact` in a
long session, then ask for the phrase again).

### Optional: `mindslice` in the user's own terminal

The plugin's command is only on the Bash tool's `PATH`: at session start the plugin writes a small launcher
to its data directory and puts that directory on the Bash tool's `PATH`. If the user wants the command in
their own terminal (for example to run `mindslice review` themselves), offer to link that launcher, after
showing them the command:

```bash
mkdir -p ~/.local/bin && ln -sf "$(command -v mindslice)" ~/.local/bin/mindslice
```

The launcher's path does not change between plugin versions (the plugin refreshes it at every session start),
so the link keeps working after updates; uninstalling the plugin removes the launcher and leaves the link
dangling. Skip it when the user already has a `mindslice` installed from PyPI or a checkout.

On Windows, Git Bash can use the same link. For cmd and PowerShell, give the user the full path of the
launcher's `mindslice.cmd`, next to it in the same directory (`cygpath -w "$(command -v mindslice).cmd"` in the
Bash tool prints it); it also stays the same across plugin updates.

## Migrating from a manual MindSlice setup

If MindSlice was set up by hand before (the `mindslice-setup` skill or the README), the old configuration
now delivers the memory a second time and exposes a second set of tools. Look for it, show the user what
you found, and remove it **only after they agree**, editing surgically so every other entry stays valid:

- **MCP server**: run `claude mcp list` (in each project the user names, too: project and local servers
  show only there) and look for a server other than `plugin:mindslice:mindslice` whose command runs
  `mindslice ... mcp`; `claude mcp get <name>` shows its command and scope. Remove it with
  `claude mcp remove <name> -s <scope>`. Note the `-w` path it used: if it differs from the plugin's
  workspace, ask which one the user wants to keep (Step 3).
- **Hooks**: ask the user to open `/hooks` and look under `SessionStart` (and other events) for a hook that
  runs `mindslice ... boot` and is not the plugin's, then delete it there. Do not read Claude's own settings
  or configuration files yourself: they can hold the user's credentials.
- **Standing rule**: `~/.claude/CLAUDE.md` and project `CLAUDE.md` files, for the paragraph that tells the
  agent to call the MindSlice server's `manifest` tool. The plugin's MCP server instructions replace it.
- **The PyPI/checkout `mindslice` command** itself can stay; the plugin does not use it. Removing a
  `MINDSLICE_WORKSPACE` export from a shell profile is worth suggesting: it overrides the plugin's choice of
  workspace for every `mindslice` command.

Then start a new session and run `mindslice plugin-status` and the Step 4 checks again.
