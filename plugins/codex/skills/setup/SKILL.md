---
name: setup
description: Set up the MindSlice memory plugin in Codex: trust its startup hook, choose or connect the memory workspace with `mindslice plugin-config`, seed it (an existing workspace, mounted slices or Markdown folders, or a short conversation), clean up an older manual MindSlice setup, and verify with `mindslice plugin-status`, `mindslice doctor` and a fresh `codex exec` session.
---

# MindSlice setup (plugin)

This plugin has already done what a manual MindSlice setup does by hand: it ships the `mindslice` engine and
command, registers the MindSlice MCP server (`mindslice`, tools `manifest`, `search`, `read`, `write`), and
delivers the user's standing memory through its own `SessionStart` hook at every session start, resume,
clear, fork and compaction. **Do not install the `mindslice` package, register another MindSlice MCP server
(`codex mcp add`), add `boot` hooks or add a "call manifest" rule to `AGENTS.md`**: that would load the memory
twice. What is left is trusting the hook, the workspace (where it lives, how to seed it), and checking that a
new session receives it.

The user may have said no more than "set up MindSlice". That is a request for the whole procedure below, in
order.

Placeholders used below:

- `<mindslice_bin>`: the plugin's `mindslice` command, by the absolute path the standing memory pages give (typically `~/.codex/plugins/data/mindslice-mindslice/bin/mindslice`); before the plugin's hook has run once, use `<plugin root>/bin/mindslice`, where `<plugin root>` is the folder two levels above this skill's directory (it holds `.codex-plugin/`). Without `-w` it uses the plugin's workspace, unless the current directory is inside another MindSlice workspace. Codex's sandbox keeps shell commands from writing outside the project, so run it with escalated permissions, which the user approves.
- `<workspace>`: the absolute path in the plugin's settings (`<mindslice_bin> plugin-config` shows it; `mindslice plugin-status` prints it too).

**When something fails, go by the error report.** A failing `mindslice` command prints
`error [code]: message` on stderr, often with `Next:` steps; `mindslice doctor` prints a `Next:` line
under every failed check. Follow those, fix the cause and re-run, rather than working around the
failure or guessing at a configuration.

## Step 1 - Check the plugin

Run `<mindslice_bin> plugin-status` with the shell tool. It prints the configured workspace, the engine version, how much of the startup capacity the
standing memory uses, and the result of a handshake with the plugin's own MCP entry point.

- **No "MindSlice standing memory" pages in this session** (no `[MindSlice standing memory · page 1/n]` text
  in your context, and no `[MindSlice plugin: ...]` notice): Codex skips a plugin's hooks until the user trusts
  them. Ask the user to run `/hooks` in Codex, review the MindSlice `SessionStart` hook (it runs
  `adapter/hook.py` from the plugin folder) and trust it; Codex asks again after every plugin update, because
  the trusted definition changed. Until then, use `<plugin root>/bin/mindslice` (see the placeholders above).
  If the MCP tools are missing too, the plugin is not installed or not enabled: ask the user to open
  `/plugins`, check that `mindslice` is installed and enabled, and start a new session.
- **Python error** (`needs Python >= 3.12`, or `Python 3.12 or newer is required`): help the user install
  Python 3.12 or newer (Homebrew, the distribution's package, `uv python install 3.12`, or pyenv; on Windows
  the python.org installer). The plugin finds `python3.12`/`python3.13` on `PATH`, in `/opt/homebrew/bin`,
  `/usr/local/bin`, `~/.local/bin` and `~/.pyenv/shims`, and on Windows every interpreter the `py` launcher
  lists. Then start a new session.
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
- Explain how to reconnect and open a fresh session, how standing context loads at session start and after compaction (the plugin's `SessionStart` hook delivers it on every start, resume, clear, fork and compaction, once the user has trusted it; the MCP server's instructions tell the model to call `manifest` if the pages are missing), which of the new-session checks you ran yourself with what result, and what remains unverified. Provide a standing-context check when applicable and a source-backed retrieval question for document imports. Reuse the builder's acceptance examples, with brief expected facts and links to source evidence; do not hand over questions whose answers the user has no way to check.
- Link the Forge report, ledgers and acceptance note for converted documents and the [review/bake workflow](https://github.com/pancerZH/MindSlice/blob/f220705059d8721d4042c452b88daa20822318b0/docs/workflow.md). Mention `review` when proposals are pending; avoid a full command tutorial or a list of every card/configuration path. Keep slice paths, dependencies, detailed results and setup configuration details in the ledger when one exists.

Aim for a short summary, a few actionable checks and links to details. Do not repeat the builder's
entire report when this setup skill calls it. Be clear that active overlay memory is already saved;
bake creates reusable versions, and future standing-card edits wait for approval. For later
disconnection or removal, use [`uninstall.md`](uninstall.md).

### Codex: the new-session checks

`codex exec` starts a one-shot session that loads the same plugins, hooks and MCP servers as one the user
opens, so run the checks through it yourself (from the user's project directory, with stdin closed, or it
waits for more input). It runs only hooks the user has trusted. `codex exec` cannot forbid single tools, so ask
the model not to call any and check that its answer names no tool call; a correct phrase can then only come
from the startup pages:

```bash
codex exec "Without calling any tool: what is the phrase in your MindSlice always-loaded memory? Answer NONE if you do not have one." < /dev/null
```

For the memory lookup, ask a question only a card can answer, without that restriction, and check the answer
used the MindSlice `search` or `read` tool. Plant and remove the temporary standing card with
`<mindslice_bin> write ... --load always --no-stage` and `--op delete` as `doctor` describes. A compaction
cannot be triggered from `codex exec`: hand the user that check (run `/compact` in a long session, then ask
for the phrase again).

### Optional: `mindslice` in the user's own terminal

If the user wants the command in their own terminal (for example to run `mindslice review` themselves), offer
to link the plugin's launcher, after showing them the command:

```bash
mkdir -p ~/.local/bin && ln -sf "<mindslice_bin>" ~/.local/bin/mindslice
```

The launcher's path does not change between plugin versions (the plugin refreshes it at every session start),
so the link keeps working after updates; uninstalling the plugin leaves it dangling. Skip it when the user
already has a `mindslice` installed from PyPI or a checkout. On Windows, cmd and PowerShell use the
`mindslice.cmd` next to the launcher.

## Migrating from a manual MindSlice setup

If MindSlice was set up by hand before (the `mindslice-setup` skill or the README), the old configuration
now delivers the memory a second time and exposes a second set of tools. Look for it, show the user what
you found, and remove it **only after they agree**, editing surgically so every other entry stays valid:

- **MCP server**: `codex mcp list` shows the servers configured in `~/.codex/config.toml` (and in a trusted
  project's `.codex/config.toml`): look for one other than the plugin's whose command runs
  `mindslice ... mcp`, and remove it with `codex mcp remove <name>`. Note the `-w` path it used: if it differs
  from the plugin's workspace, ask which one the user wants to keep (Step 3).
- **Hooks**: `~/.codex/hooks.json`, `[hooks]` tables in `~/.codex/config.toml`, and a project's
  `.codex/hooks.json` or `.codex/config.toml`, for a hook that runs `mindslice ... boot`. Do not touch the
  `[hooks.state...]` entries: they record which hooks the user trusted.
- **Standing rule**: `~/.codex/AGENTS.md` and project `AGENTS.md` files, for the paragraph that tells the
  agent to call the MindSlice server's `manifest` tool. The plugin's startup pages and MCP server
  instructions replace it.
- **The PyPI/checkout `mindslice` command** itself can stay; the plugin does not use it. Removing a
  `MINDSLICE_WORKSPACE` export from a shell profile is worth suggesting: it overrides the plugin's choice of
  workspace for every `mindslice` command.

Do not read `~/.codex/auth.json`: it holds the user's credentials. Then start a new session and run
`mindslice plugin-status` and the Step 4 checks again.
