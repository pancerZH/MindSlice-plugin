# Uninstall or disconnect the MindSlice plugin (Antigravity)

Removing the plugin removes its MCP server, hook, rule, skills and `mindslice` command. **The memory workspace
on disk is kept unless the user explicitly asks to delete it.**

## Step 1 - Inspect

1. Run `mindslice plugin-status` with the terminal tool and note the workspace path (`<workspace>`).
2. Check what the workspace holds: `<workspace>/overlay/` and `<workspace>/staging/` (cards and pending
   changes), `<workspace>/slices/`, and the external folders listed in `<workspace>/mounts.toml`.
3. Check for leftovers outside the plugin: a `~/.local/bin/mindslice` link to the plugin's `bin/mindslice`
   (`ls -l ~/.local/bin/mindslice`), and any manual MindSlice MCP server, `boot` hook or `GEMINI.md`/`AGENTS.md`
   rule (see "Migrating from a manual MindSlice setup" in [SKILL.md](SKILL.md)).

## Step 2 - Confirm with the user (mandatory)

Ask the user, in their language, three separate questions, and wait for the answers:

1. Uninstall the plugin, or only **disable** it (keeps it installed and its settings for later)?
2. Remove the leftovers found in Step 1 (the link, manual configuration)?
3. **Also delete the workspace folder `<workspace>`?** Default: keep it. State the exact path and what it
   holds. Keeping it leaves every Markdown card on disk; deleting it permanently removes `overlay/`,
   `staging/` and `slices/`. External folders mounted via `mounts.toml` are never deleted.

## Step 3 - Remove the plugin

The user does this: in the CLI, `/plugin`, select **mindslice**, then `space` to disable it or `ctrl+s` to
uninstall it; from a shell, `agy plugin disable mindslice` or `agy plugin uninstall mindslice`; in the
Antigravity app or IDE, `[mindslice](customization://mindslice)` (keyed on the install folder name if
different) on the Customizations page. Uninstalling also clears the plugin's settings.

Remove only the leftovers the user agreed to: `rm ~/.local/bin/mindslice` only if it is a link to the plugin's
`bin/mindslice` (uninstalling removes the target, so the link would dangle); manual configuration as the setup
skill's migration section describes. The plugin's data folder (`plugin_data/mindslice` under
`~/.gemini/antigravity-cli/`, `~/.gemini/antigravity/` or `~/.gemini/antigravity-ide/`, holding the engine copy
and `active_workspace.json`) can be deleted too.

## Step 4 - Delete the workspace (only if the user explicitly asked)

- Verify `<workspace>` is neither `/` nor `$HOME`, and that `<workspace>/mounts.toml` exists
  (`test -f "<workspace>/mounts.toml"`), so you never delete a folder that is not a MindSlice workspace.
- Read `<workspace>/mounts.toml` and make sure no mounted folder you would remove lies outside
  `<workspace>`; never touch those.
- Delete `<workspace>`. If the user chose to keep it, leave it and tell them its path.

## Step 5 - Verify

Ask the user to start a new conversation and check that the MindSlice tools and the "MindSlice standing
memory" pages are gone. Summarize what was removed and whether `<workspace>` was kept.
