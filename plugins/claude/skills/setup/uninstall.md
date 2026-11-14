# Uninstall or disconnect the MindSlice plugin (Claude Code)

Removing the plugin removes its MCP server, hooks, skills and `mindslice` command. **The memory workspace
on disk is kept unless the user explicitly asks to delete it.**

## Step 1 - Inspect

1. Run `mindslice plugin-status` in the Bash tool and note the workspace path (`<workspace>`).
2. Check what the workspace holds: `<workspace>/overlay/` and `<workspace>/staging/` (cards and pending
   changes), `<workspace>/slices/`, and the external folders listed in `<workspace>/mounts.toml`.
3. Check for leftovers outside the plugin: a `~/.local/bin/mindslice` link pointing into the plugin's
   directory (`ls -l ~/.local/bin/mindslice`), and any manual MindSlice MCP server, `boot` hook or
   `CLAUDE.md` rule (see "Migrating from a manual MindSlice setup" in [SKILL.md](SKILL.md)).

## Step 2 - Confirm with the user (mandatory)

Ask the user, in their language, three separate questions, and wait for the answers:

1. Uninstall the plugin, or only **disable** it (keeps it installed for later)?
2. Remove the leftovers found in Step 1 (the link, manual configuration)?
3. **Also delete the workspace folder `<workspace>`?** Default: keep it. State the exact path and what it
   holds. Keeping it leaves every Markdown card on disk; deleting it permanently removes `overlay/`,
   `staging/` and `slices/`. External folders mounted via `mounts.toml` are never deleted.

## Step 3 - Remove the plugin

The user runs, in Claude Code: `/plugin uninstall mindslice@mindslice` (or `/plugin disable
mindslice@mindslice`). From a shell: `claude plugin uninstall mindslice@mindslice`. The marketplace can stay;
`/plugin marketplace remove mindslice` removes it too.

Remove only the leftovers the user agreed to: `rm ~/.local/bin/mindslice` only if it is a link into the
plugin; manual configuration as the setup skill's migration section describes.

## Step 4 - Delete the workspace (only if the user explicitly asked)

- Verify `<workspace>` is neither `/` nor `$HOME`, and that `<workspace>/mounts.toml` exists
  (`test -f "<workspace>/mounts.toml"`), so you never delete a folder that is not a MindSlice workspace.
- Read `<workspace>/mounts.toml` and make sure no mounted folder you would remove lies outside
  `<workspace>`; never touch those.
- Delete `<workspace>`. If the user chose to keep it, leave it and tell them its path.

## Step 5 - Verify

Ask the user to start a new session (the current one keeps the tools it started with) and check that the
`mcp__plugin_mindslice_mindslice__*` tools and the "MindSlice standing memory" pages are gone. Summarize
what was removed and whether `<workspace>` was kept.
